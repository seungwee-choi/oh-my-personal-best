"""Unit tests for scripts/weekplan.py.

Run: python3 tests/test_weekplan.py  (stdlib only; no pytest required).
"""
import datetime as _dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import weekplan  # noqa: E402
from ompb_env import local_today  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _monday_of(date: _dt.date) -> _dt.date:
    return date - _dt.timedelta(days=date.weekday())


def _write_plan(home: str, filename: str, plan: dict) -> None:
    with open(os.path.join(home, filename), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)


def _make_plan(monday: _dt.date) -> dict:
    """Minimal plan dict with 7 days starting on ``monday``."""
    days = []
    dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i in range(7):
        d = monday + _dt.timedelta(days=i)
        days.append({"date": d.isoformat(), "dow": dow[i], "type": "easy", "distance_km": 8.0})
    return {"week": {"start_date": monday.isoformat(), "end_date": (monday + _dt.timedelta(days=6)).isoformat()},
            "days": days}


# ── week_range ────────────────────────────────────────────────────────────────

def test_week_range_offset0_is_monday_to_sunday():
    start, end = weekplan.week_range(0)
    s = _dt.date.fromisoformat(start)
    e = _dt.date.fromisoformat(end)
    assert s.weekday() == 0, f"start must be Monday, got {s.strftime('%A')}"
    assert e.weekday() == 6, f"end must be Sunday, got {e.strftime('%A')}"
    assert (e - s).days == 6


def test_week_range_offset_plus1():
    start0, _ = weekplan.week_range(0)
    start1, _ = weekplan.week_range(1)
    s0 = _dt.date.fromisoformat(start0)
    s1 = _dt.date.fromisoformat(start1)
    assert (s1 - s0).days == 7


def test_week_range_offset_minus1():
    start0, _ = weekplan.week_range(0)
    start_m1, _ = weekplan.week_range(-1)
    s0 = _dt.date.fromisoformat(start0)
    s_m1 = _dt.date.fromisoformat(start_m1)
    assert (s0 - s_m1).days == 7


def test_week_range_start_is_monday():
    for off in (-2, -1, 0, 1, 2):
        start, end = weekplan.week_range(off)
        s = _dt.date.fromisoformat(start)
        e = _dt.date.fromisoformat(end)
        assert s.weekday() == 0
        assert e.weekday() == 6


# ── offset_for_date ───────────────────────────────────────────────────────────

def test_offset_for_date_this_week():
    today = local_today()
    this_monday = _monday_of(today)
    # any day in this week → offset 0
    for i in range(7):
        d = (this_monday + _dt.timedelta(days=i)).isoformat()
        assert weekplan.offset_for_date(d) == 0, f"expected 0 for {d}"


def test_offset_for_date_next_week():
    today = local_today()
    next_monday = _monday_of(today) + _dt.timedelta(days=7)
    assert weekplan.offset_for_date(next_monday.isoformat()) == 1


def test_offset_for_date_last_week():
    today = local_today()
    last_monday = _monday_of(today) - _dt.timedelta(days=7)
    assert weekplan.offset_for_date(last_monday.isoformat()) == -1


def test_offset_for_date_round_trip():
    today = local_today()
    for off in (-3, -2, -1, 0, 1, 2, 3):
        start, _ = weekplan.week_range(off)
        assert weekplan.offset_for_date(start) == off, \
            f"round-trip failed for offset {off}: date={start}"


# ── week_plan_path ────────────────────────────────────────────────────────────

def test_week_plan_path_offset0_is_plan_week_json():
    tmp = tempfile.mkdtemp()
    path = weekplan.week_plan_path(tmp, 0)
    assert os.path.basename(path) == "plan-week.json"
    assert path.startswith(tmp)


def test_week_plan_path_nonzero_uses_monday_date():
    tmp = tempfile.mkdtemp()
    for off in (1, -1, 2):
        path = weekplan.week_plan_path(tmp, off)
        fname = os.path.basename(path)
        assert fname.startswith("plan-week-"), f"unexpected filename: {fname}"
        assert fname.endswith(".json")
        # embedded date must be a Monday
        date_part = fname[len("plan-week-"):-len(".json")]
        d = _dt.date.fromisoformat(date_part)
        assert d.weekday() == 0, f"filename date is not Monday: {d}"


# ── archive_if_stale ──────────────────────────────────────────────────────────

def test_archive_if_stale_current_week_is_noop():
    tmp = tempfile.mkdtemp()
    today = local_today()
    this_monday = _monday_of(today)
    plan = _make_plan(this_monday)
    _write_plan(tmp, "plan-week.json", plan)
    changed = weekplan.archive_if_stale(tmp)
    assert not changed
    assert os.path.isfile(os.path.join(tmp, "plan-week.json"))


def test_archive_if_stale_archives_past_week():
    tmp = tempfile.mkdtemp()
    today = local_today()
    last_monday = _monday_of(today) - _dt.timedelta(days=7)
    plan = _make_plan(last_monday)
    _write_plan(tmp, "plan-week.json", plan)

    changed = weekplan.archive_if_stale(tmp)
    assert changed
    # stale plan-week.json must be gone
    assert not os.path.isfile(os.path.join(tmp, "plan-week.json"))
    # archive must exist
    archive = os.path.join(tmp, f"plan-week-{last_monday.isoformat()}.json")
    assert os.path.isfile(archive)


def test_archive_if_stale_promotes_premade_plan():
    tmp = tempfile.mkdtemp()
    today = local_today()
    this_monday = _monday_of(today)
    # write a pre-made plan under the dated name (as if created last week for this week)
    plan = _make_plan(this_monday)
    src = os.path.join(tmp, f"plan-week-{this_monday.isoformat()}.json")
    with open(src, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    # no plan-week.json yet
    assert not os.path.isfile(os.path.join(tmp, "plan-week.json"))

    changed = weekplan.archive_if_stale(tmp)
    assert changed
    assert os.path.isfile(os.path.join(tmp, "plan-week.json"))


def test_archive_if_stale_no_file_is_noop():
    tmp = tempfile.mkdtemp()
    changed = weekplan.archive_if_stale(tmp)
    assert not changed


def test_archive_if_stale_idempotent():
    tmp = tempfile.mkdtemp()
    today = local_today()
    last_monday = _monday_of(today) - _dt.timedelta(days=7)
    plan = _make_plan(last_monday)
    _write_plan(tmp, "plan-week.json", plan)

    weekplan.archive_if_stale(tmp)
    # calling again must not raise or corrupt
    weekplan.archive_if_stale(tmp)
    archive = os.path.join(tmp, f"plan-week-{last_monday.isoformat()}.json")
    assert os.path.isfile(archive)


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as exc:
                import traceback
                print(f"  FAIL  {name}: {exc}")
                traceback.print_exc()
                failed += 1
    print(f"\nweekplan: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
