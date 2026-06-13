"""Unit tests for the HR-zone module (scripts/zones.py).

Run: `python3 tests/test_zones.py`  (stdlib only; no pytest required).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import zones  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_log(home, entries):
    path = os.path.join(home, "training-log.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _run(avg_hr=None, max_hr=None, pace=None, distance_km=10.0):
    actual = {"distance_km": distance_km}
    if avg_hr is not None:
        actual["avg_hr"] = avg_hr
    if max_hr is not None:
        actual["max_hr"] = max_hr
    if pace is not None:
        actual["pace"] = pace
    return {"date": "2026-01-01", "sport": "running", "type": "easy", "actual": actual}


# ---------------------------------------------------------------------------
# Zone-table math
# ---------------------------------------------------------------------------

def test_zone_edges_for_hrmax_190():
    """Known HRmax=190 → check every zone's bpm edges."""
    table = zones._zone_table(190)
    assert len(table) == 5

    z1 = table[0]
    assert z1["zone"] == "Z1"
    assert z1["lo_bpm"] is None          # Z1 lower edge is open (0 bpm)
    assert z1["hi_bpm"] == round(0.60 * 190)   # 114

    z2 = table[1]
    assert z2["lo_bpm"] == round(0.60 * 190)   # 114
    assert z2["hi_bpm"] == round(0.70 * 190)   # 133

    z3 = table[2]
    assert z3["lo_bpm"] == round(0.70 * 190)   # 133
    assert z3["hi_bpm"] == round(0.80 * 190)   # 152

    z4 = table[3]
    assert z4["lo_bpm"] == round(0.80 * 190)   # 152
    assert z4["hi_bpm"] == round(0.90 * 190)   # 171

    z5 = table[4]
    assert z5["zone"] == "Z5"
    assert z5["lo_bpm"] == round(0.90 * 190)   # 171
    assert z5["hi_bpm"] is None          # Z5 upper edge is open-ended


def test_zone_pct_labels():
    table = zones._zone_table(190)
    assert table[0]["lo_pct"] == 0  and table[0]["hi_pct"] == 60
    assert table[1]["lo_pct"] == 60 and table[1]["hi_pct"] == 70
    assert table[4]["lo_pct"] == 90 and table[4]["hi_pct"] == 100


def test_zone_names_are_korean():
    table = zones._zone_table(190)
    names = [z["name"] for z in table]
    assert names == ["회복", "유산소(이지)", "템포(역치 아래)", "역치", "VO2max"]


def test_hrmax_estimated_p99():
    """99th-pct of max HR values is preferred."""
    max_hrs = list(range(150, 200))   # 50 values; P99 ≈ 199
    est = zones._hrmax_estimated(max_hrs, [])
    assert est is not None
    assert 195 <= est <= 199


def test_hrmax_estimated_fallback_to_avg():
    """No max_hr data → 1.10 × highest avg_hr."""
    est = zones._hrmax_estimated([], [140, 155, 160])
    assert est == 160 * 1.10


def test_hrmax_estimated_none_on_empty():
    assert zones._hrmax_estimated([], []) is None


# ---------------------------------------------------------------------------
# set_hrmax / clear_hrmax round-trip
# ---------------------------------------------------------------------------

def test_set_hrmax_round_trip():
    with tempfile.TemporaryDirectory() as home:
        result = zones.set_hrmax(home, 185)
        assert result["hrmax"] == 185
        assert result["source"] == "manual"
        # config.json must persist it
        cfg = json.loads(open(os.path.join(home, "config.json"), encoding="utf-8").read())
        assert cfg["hrmax"] == 185


def test_set_hrmax_preserves_other_keys():
    with tempfile.TemporaryDirectory() as home:
        # pre-populate config with language setting
        with open(os.path.join(home, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"language": "ko"}, fh)
        zones.set_hrmax(home, 190)
        cfg = json.loads(open(os.path.join(home, "config.json"), encoding="utf-8").read())
        assert cfg["language"] == "ko"
        assert cfg["hrmax"] == 190


def test_clear_hrmax_removes_override():
    with tempfile.TemporaryDirectory() as home:
        zones.set_hrmax(home, 185)
        result = zones.clear_hrmax(home)
        # no log entries → source should be "none"
        assert result["source"] in ("none", "estimated")
        cfg = json.loads(open(os.path.join(home, "config.json"), encoding="utf-8").read())
        assert "hrmax" not in cfg


def test_set_hrmax_rejects_out_of_range():
    with tempfile.TemporaryDirectory() as home:
        try:
            zones.set_hrmax(home, 100)
            assert False, "should have raised ValueError"
        except ValueError:
            pass
        try:
            zones.set_hrmax(home, 240)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# current() on an empty home
# ---------------------------------------------------------------------------

def test_current_empty_home():
    with tempfile.TemporaryDirectory() as home:
        result = zones.current(home)
        assert result["hrmax"] is None
        assert result["source"] == "none"
        assert result["zones"] == []
        assert result["hr_runs"] == 0


def test_current_with_log_estimates_hrmax():
    with tempfile.TemporaryDirectory() as home:
        entries = [_run(avg_hr=140 + i, max_hr=165 + i, pace="5:30") for i in range(20)]
        _write_log(home, entries)
        result = zones.current(home)
        assert result["hrmax"] is not None
        assert result["source"] == "estimated"
        assert result["hr_runs"] == 20
        assert len(result["zones"]) == 5


def test_current_manual_overrides_estimated():
    with tempfile.TemporaryDirectory() as home:
        entries = [_run(avg_hr=140, max_hr=165, pace="5:30") for _ in range(10)]
        _write_log(home, entries)
        zones.set_hrmax(home, 200)
        result = zones.current(home)
        assert result["hrmax"] == 200
        assert result["source"] == "manual"
        assert result["estimated_hrmax"] is not None  # log estimate still reported


def test_current_non_run_ignored():
    with tempfile.TemporaryDirectory() as home:
        entries = [
            {"date": "2026-01-01", "sport": "cycling", "type": "cross",
             "actual": {"avg_hr": 150, "max_hr": 180}},
        ]
        _write_log(home, entries)
        result = zones.current(home)
        assert result["hr_runs"] == 0
        assert result["hrmax"] is None


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {name}: {exc}")
                failed += 1
    print(f"\nzones: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
