"""Unit tests for scripts/logquery.py.

Run: python3 tests/test_logquery.py  (stdlib only; no pytest required).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import logquery  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_home(entries):
    """Create a temp OMPB home dir with training-log.jsonl from ``entries``."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "training-log.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return tmp


ENTRIES = [
    {"date": "2026-01-05", "sport": "running", "type": "easy",
     "actual": {"distance_km": 8.0, "pace": "5:30"}},
    {"date": "2026-01-07", "sport": "running", "type": "long",
     "actual": {"distance_km": 20.0, "pace": "6:00"}},
    {"date": "2026-01-12", "sport": "running", "type": "tempo",
     "actual": {"distance_km": 10.0, "pace": "4:30"}},
    {"date": "2026-01-14", "sport": "cycling", "type": "cross",
     "actual": {"distance_km": 30.0}},
    {"date": "2026-01-19", "sport": "running", "type": "interval",
     "actual": {"distance_km": 12.0, "pace": "4:00"}},
]


# ── load_log ──────────────────────────────────────────────────────────────────

def test_load_log_basic():
    home = _make_home(ENTRIES)
    rows = logquery.load_log(home)
    assert len(rows) == 5


def test_load_log_skips_blank_and_bad():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "training-log.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"date":"2026-01-01","sport":"running"}\n')
        fh.write("\n")           # blank line
        fh.write("not json\n")  # bad line
        fh.write('{"date":"2026-01-02","sport":"running"}\n')
    rows = logquery.load_log(tmp)
    assert len(rows) == 2


def test_load_log_missing_file():
    tmp = tempfile.mkdtemp()
    rows = logquery.load_log(tmp)
    assert rows == []


# ── query_log ─────────────────────────────────────────────────────────────────

def test_query_log_date_sorted():
    home = _make_home(list(reversed(ENTRIES)))  # written in reverse order
    rows = logquery.query_log(home)
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)


def test_query_log_since_until():
    home = _make_home(ENTRIES)
    rows = logquery.query_log(home, since="2026-01-10", until="2026-01-15")
    assert all("2026-01-10" <= r["date"] <= "2026-01-15" for r in rows)
    assert len(rows) == 2  # Jan 12 (tempo) + Jan 14 (cycling)


def test_query_log_sport_filter():
    home = _make_home(ENTRIES)
    rows = logquery.query_log(home, sport="running")
    assert all(r.get("sport") == "running" for r in rows)
    assert len(rows) == 4


def test_query_log_type_filter():
    home = _make_home(ENTRIES)
    rows = logquery.query_log(home, type="long")
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-07"


def test_query_log_limit_keeps_last_n():
    home = _make_home(ENTRIES)
    rows = logquery.query_log(home, limit=2)
    assert len(rows) == 2
    assert rows[-1]["date"] == "2026-01-19"


def test_query_log_combined_filters():
    home = _make_home(ENTRIES)
    rows = logquery.query_log(home, sport="running", since="2026-01-10")
    assert len(rows) == 2  # tempo (Jan 12) + interval (Jan 19)


# ── weekly_load ───────────────────────────────────────────────────────────────

def test_weekly_load_bucketing():
    home = _make_home(ENTRIES)
    rows = logquery.weekly_load(home, weeks=52)
    # Jan 5 + Jan 7 → ISO week 2026-W02; Jan 12 + Jan 14 → W03; Jan 19 → W04
    keys = [r["week"] for r in rows]
    assert "2026-W02" in keys
    assert "2026-W03" in keys
    assert "2026-W04" in keys


def test_weekly_load_distance_sum():
    home = _make_home(ENTRIES)
    rows = logquery.weekly_load(home, weeks=52)
    w02 = next(r for r in rows if r["week"] == "2026-W02")
    assert abs(w02["distance_km"] - 28.0) < 0.01  # 8 + 20


def test_weekly_load_sessions_count():
    home = _make_home(ENTRIES)
    rows = logquery.weekly_load(home, weeks=52)
    w03 = next(r for r in rows if r["week"] == "2026-W03")
    assert w03["sessions"] == 2  # tempo + cycling (cross counts as a session)


def test_weekly_load_limit_weeks():
    # Build 4 weeks of data, ask for only 2 most recent
    entries = []
    for w in range(4):
        entries.append({"date": f"2026-01-{5 + w * 7:02d}", "sport": "running",
                        "type": "easy", "actual": {"distance_km": 10.0}})
    home = _make_home(entries)
    rows = logquery.weekly_load(home, weeks=2)
    assert len(rows) == 2


def test_weekly_load_oldest_to_newest():
    home = _make_home(ENTRIES)
    rows = logquery.weekly_load(home, weeks=52)
    weeks = [r["week"] for r in rows]
    assert weeks == sorted(weeks)


# ── is_run ────────────────────────────────────────────────────────────────────

def test_is_run_running_sport():
    assert logquery.is_run({"sport": "running", "type": "easy"}) is True


def test_is_run_missing_sport_is_run():
    # CSV imports omit sport — treat as run unless cross
    assert logquery.is_run({"type": "easy"}) is True
    assert logquery.is_run({}) is True


def test_is_run_cross_type_excluded():
    assert logquery.is_run({"sport": "running", "type": "cross"}) is False
    assert logquery.is_run({"type": "cross"}) is False


def test_is_run_cycling_excluded():
    assert logquery.is_run({"sport": "cycling", "type": "cross"}) is False


# ── pace_sec ──────────────────────────────────────────────────────────────────

def test_pace_sec_normal():
    assert logquery.pace_sec("5:30") == 330
    assert logquery.pace_sec("4:00") == 240


def test_pace_sec_single_digit_seconds():
    assert logquery.pace_sec("6:05") == 365


def test_pace_sec_none_on_invalid():
    assert logquery.pace_sec(None) is None
    assert logquery.pace_sec("") is None
    assert logquery.pace_sec("nocodon") is None


def test_pace_sec_extra_colons():
    # only first two parts used
    assert logquery.pace_sec("1:05:30") == 65  # 1*60+5


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {name}: {exc}")
                failed += 1
    print(f"\nlogquery: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
