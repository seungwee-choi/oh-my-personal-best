"""Unit tests for body (weight/fuel) tracking — stdlib only, no pytest required.

Run: `python3 tests/test_body.py`

Uses a temp OMPB_HOME per test so body.jsonl / goal.json writes are isolated.
Pins 'today' to 2026-06-04 for deterministic trend/rate windows.
"""
import datetime as _dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import body as B  # noqa: E402
import ompb_env   # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = _dt.date(2026, 6, 4)

_orig_local_today = ompb_env.local_today


def _patched_today(*a, **k):
    return _TODAY


def _make_home():
    """Return a fresh temp directory to use as OMPB_HOME."""
    return tempfile.mkdtemp()


def _seed(home, pairs):
    """pairs: list of (iso_date, weight_kg)."""
    for d, w in pairs:
        B.log_weight(home, w, on_date=d)


def _with_today(fn):
    """Run fn() with local_today patched to return _TODAY, then restore."""
    ompb_env.local_today = _patched_today
    B.local_today = _patched_today
    try:
        fn()
    finally:
        ompb_env.local_today = _orig_local_today
        B.local_today = _orig_local_today


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_log_and_load_roundtrip():
    home = _make_home()

    def _run():
        e = B.log_weight(home, 72.4, bodyfat_pct=14.2, note="아침 공복")
        assert e["weight_kg"] == 72.4, f"weight_kg: {e['weight_kg']}"
        assert e["bodyfat_pct"] == 14.2, f"bodyfat_pct: {e['bodyfat_pct']}"
        assert e["source"] == "manual", f"source: {e['source']}"
        assert e["date"] == "2026-06-04", f"date: {e['date']}"
        rows = B._load(home)
        assert len(rows) == 1, f"row count: {len(rows)}"
        assert rows[0]["note"] == "아침 공복", f"note: {rows[0].get('note')}"

    _with_today(_run)


def test_trend_none_when_empty():
    home = _make_home()

    def _run():
        assert B.trend(home) is None
        assert B.summary(home) is None
        assert B.race_weight(home) is None
        assert B.under_fueling_flag(home) is None

    _with_today(_run)


def test_trend_basic():
    home = _make_home()

    def _run():
        _seed(home, [("2026-05-05", 74.0), ("2026-05-20", 73.0),
                     ("2026-05-28", 72.4), ("2026-06-03", 72.0)])
        t = B.trend(home)
        assert t["current"] == 72.0, f"current: {t['current']}"
        assert t["current_date"] == "2026-06-03", f"current_date: {t['current_date']}"
        assert t["n"] == 4, f"n: {t['n']}"
        # 05-28 (6 days before 06-04) and 06-03 (1 day before 06-04) both within 7d window
        assert t["ma7"] == 72.2, f"ma7: {t['ma7']}"
        assert t["min"] == 72.0 and t["max"] == 74.0, f"min/max: {t['min']}/{t['max']}"
        assert t["spark"][-1] == 72.0, f"spark[-1]: {t['spark'][-1]}"
        assert t["rate_kg_wk"] is not None and t["rate_kg_wk"] < 0, \
            f"rate_kg_wk: {t['rate_kg_wk']}"

    _with_today(_run)


def test_rate_needs_min_span():
    home = _make_home()

    def _run():
        # two points 2 days apart → span < 3 → no weekly estimate
        _seed(home, [("2026-06-02", 72.0), ("2026-06-03", 71.8)])
        assert B.trend(home)["rate_kg_wk"] is None

    _with_today(_run)


def test_race_weight_progress_and_safety():
    home = _make_home()

    def _run():
        # current ~72.0, target 70.0 → need -2.0kg; race 10 weeks out → -0.2/wk ≈ 0.28%/wk (safe)
        _seed(home, [("2026-05-28", 72.2), ("2026-06-03", 72.0)])
        B._write_goal(home, {"event": "Marathon", "distance": "full",
                             "target_time": "2:59:00", "race_date": "2026-08-13"})
        B.set_target_weight(home, 70.0)
        assert B.target_weight(home) == 70.0, f"target_weight: {B.target_weight(home)}"
        rw = B.race_weight(home)
        assert rw["target_kg"] == 70.0, f"target_kg: {rw['target_kg']}"
        assert rw["gap_kg"] < 0, f"gap_kg: {rw['gap_kg']}"
        assert abs(rw["weeks_left"] - 10.0) < 0.3, f"weeks_left: {rw['weeks_left']}"
        assert rw["weekly_needed_kg_wk"] < 0, f"weekly_needed_kg_wk: {rw['weekly_needed_kg_wk']}"
        assert rw["safe"] is True, f"safe: {rw['safe']}"
        assert rw["on_track"] is True, f"on_track: {rw['on_track']}"

    _with_today(_run)


def test_race_weight_goal_keys_preserved():
    """set_target_weight must not clobber existing race goal keys."""
    home = _make_home()
    B._write_goal(home, {"event": "Seoul Marathon", "target_time": "3:30:00",
                          "race_date": "2026-11-01", "distance": "full"})
    B.set_target_weight(home, 71.5)
    g = B._read_goal(home)
    assert g.get("event") == "Seoul Marathon", f"event clobbered: {g}"
    assert g.get("target_time") == "3:30:00", f"target_time clobbered: {g}"
    assert g.get("race_date") == "2026-11-01", f"race_date clobbered: {g}"
    assert g.get("target_weight_kg") == 71.5, f"target_weight_kg: {g.get('target_weight_kg')}"


def test_race_weight_unsafe_when_too_aggressive():
    home = _make_home()

    def _run():
        # need -4kg in 2 weeks → -2/wk ≈ 2.8%/wk → unsafe
        _seed(home, [("2026-05-28", 72.2), ("2026-06-03", 72.0)])
        B._write_goal(home, {"event": "Marathon", "distance": "full",
                             "target_time": "2:59:00", "race_date": "2026-06-18"})
        B.set_target_weight(home, 68.0)
        rw = B.race_weight(home)
        assert rw["safe"] is False, f"safe: {rw['safe']}"
        assert rw["on_track"] is False, f"on_track: {rw['on_track']}"

    _with_today(_run)


def test_under_fueling_flag():
    home = _make_home()

    def _run():
        # ~1kg drop over 7 days on a ~72kg runner ≈ 1.4%/wk → flagged
        _seed(home, [("2026-05-27", 73.0), ("2026-05-31", 72.4), ("2026-06-03", 72.0)])
        uf = B.under_fueling_flag(home)
        assert uf is not None, "expected under_fueling_flag to fire"
        assert uf["pct_per_week"] >= 1.0, f"pct_per_week: {uf['pct_per_week']}"
        assert "1%/주" in uf["msg"], f"msg: {uf['msg']}"

    _with_today(_run)


def test_no_under_fueling_when_stable():
    home = _make_home()

    def _run():
        _seed(home, [("2026-05-20", 72.0), ("2026-05-27", 72.1), ("2026-06-03", 72.0)])
        assert B.under_fueling_flag(home) is None

    _with_today(_run)


def test_fuel_advice_by_type():
    assert "pre_carb" in B.fuel_advice("long")["flags"]
    assert "mid_fuel" in B.fuel_advice("long")["flags"]
    assert B.fuel_advice("interval")["flags"] == ["pre_carb", "post_protein"]
    assert B.fuel_advice("easy")["flags"] == []
    assert B.fuel_advice("")["note"] == ""


def test_delete_entry_fixes_typo():
    home = _make_home()

    def _run():
        B.log_weight(home, 72.0, on_date="2026-06-02")
        bad = B.log_weight(home, 27.0, on_date="2026-06-03")   # 손가락 실수
        assert B.trend(home)["min"] == 27.0
        assert B.delete_entry(home, bad["logged_at"]) is True
        t = B.trend(home)
        assert t["min"] == 72.0, f"min after delete: {t['min']}"
        assert t["n"] == 1, f"n after delete: {t['n']}"
        assert B.delete_entry(home, "no-such-ts") is False

    _with_today(_run)


def test_fuel_log_and_for():
    home = _make_home()

    def _run():
        B.log_fuel(home, source_id="strava:1", day_type="long", pre=True, during=True, post=False)
        B.log_fuel(home, source_id="strava:1", day_type="long", pre=True, during=True, post=True)
        B.log_fuel(home, source_id="strava:2", day_type="interval", pre=False, post=True)
        f = B.fuel_for(home, "strava:1")
        assert f["post"] is True, f"post: {f['post']}"
        assert f["day_type"] == "long", f"day_type: {f['day_type']}"
        assert B.fuel_for(home, "nope") is None
        assert len(B.fuel_log(home)) == 3, f"fuel_log count: {len(B.fuel_log(home))}"

    _with_today(_run)


def test_summary_composes():
    home = _make_home()

    def _run():
        _seed(home, [("2026-05-27", 73.0), ("2026-05-31", 72.4), ("2026-06-03", 72.0)])
        B._write_goal(home, {"distance": "full", "race_date": "2026-08-13"})
        B.set_target_weight(home, 70.0)
        s = B.summary(home)
        assert s is not None, "summary returned None"
        assert s["current_kg"] == 72.0, f"current_kg: {s['current_kg']}"
        assert "race_weight" in s, "race_weight missing from summary"
        assert "under_fueling_risk" in s, "under_fueling_risk missing from summary"

    _with_today(_run)


def test_recent_sorted():
    home = _make_home()

    def _run():
        _seed(home, [("2026-05-01", 74.0), ("2026-05-10", 73.5), ("2026-06-01", 72.0)])
        rows = B.recent(home, limit=2)
        assert len(rows) == 2
        # most recent first
        assert rows[0]["date"] >= rows[1]["date"]

    _with_today(_run)


# ---------------------------------------------------------------------------
# Runner
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
    print(f"\nbody tests: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
