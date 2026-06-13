"""Unit tests for scripts/review.py.

Run: python3 tests/test_review.py  (stdlib only; no pytest required).
"""
import datetime as _dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import review  # noqa: E402
from ompb_env import local_today  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _monday_of(date: _dt.date) -> _dt.date:
    return date - _dt.timedelta(days=date.weekday())


_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _make_home_with_week(plan_days_spec=None, log_entries=None):
    """Build a temp home with plan-week.json + training-log.jsonl.

    ``plan_days_spec``: list of (dow_index 0-6, type, distance_km) for the plan.
    ``log_entries``: list of (dow_index 0-6, type, distance_km) for the log.
    Dates are derived from this week's Monday.
    """
    tmp = tempfile.mkdtemp()
    today = local_today()
    this_monday = _monday_of(today)

    # build plan-week.json
    if plan_days_spec is not None:
        days = []
        for dow_i, typ, dist in plan_days_spec:
            d = (this_monday + _dt.timedelta(days=dow_i)).isoformat()
            days.append({
                "date": d, "dow": _DOW[dow_i], "type": typ, "distance_km": dist,
                "pace": "", "hr_zone": "", "title": "", "structure": "", "purpose": "",
            })
        plan = {
            "week": {
                "start_date": this_monday.isoformat(),
                "end_date": (this_monday + _dt.timedelta(days=6)).isoformat(),
                "phase": "Base", "focus": "aerobic", "target_km": 50.0,
                "plan_week": 1, "total_weeks": 16, "prev_week_km": 45.0, "ramp_pct": 11,
            },
            "days": days,
            "coach_notes": ["이번 주 계획이 준비됐어요."],
            "goal": {"event": "full", "target_time": "3:30:00"},
            "athlete": {"label": "러너"},
        }
        plan_path = os.path.join(tmp, "plan-week.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, indent=2)

    # build training-log.jsonl
    if log_entries is not None:
        log_path = os.path.join(tmp, "training-log.jsonl")
        with open(log_path, "w", encoding="utf-8") as fh:
            for dow_i, typ, dist in log_entries:
                d = (this_monday + _dt.timedelta(days=dow_i)).isoformat()
                entry = {
                    "date": d, "sport": "running", "type": typ,
                    "actual": {"distance_km": dist, "pace": "5:30", "avg_hr": 140},
                }
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return tmp, this_monday


# ── day_status ────────────────────────────────────────────────────────────────

def test_day_status_done():
    plan = {"type": "tempo", "distance_km": 10.0}
    runs = [{"date": "2026-01-05", "actual": {"distance_km": 9.8}}]
    assert review.day_status(plan, runs, is_future=False) == "done"


def test_day_status_skipped():
    plan = {"type": "easy", "distance_km": 8.0}
    assert review.day_status(plan, [], is_future=False) == "skipped"


def test_day_status_upcoming():
    plan = {"type": "long", "distance_km": 20.0}
    assert review.day_status(plan, [], is_future=True) == "upcoming"


def test_day_status_rest_kept():
    plan = {"type": "rest", "distance_km": 0}
    assert review.day_status(plan, [], is_future=False) == "rest_kept"


def test_day_status_rest_ran():
    plan = {"type": "rest", "distance_km": 0}
    runs = [{"date": "2026-01-05", "actual": {"distance_km": 5.0}}]
    assert review.day_status(plan, runs) == "rest_ran"


def test_day_status_unplanned():
    runs = [{"date": "2026-01-05", "actual": {"distance_km": 8.0}}]
    assert review.day_status(None, runs) == "unplanned"


def test_day_status_empty():
    assert review.day_status(None, []) == "empty"


def test_day_status_cross_only():
    plan = {"type": "easy", "distance_km": 8.0}
    assert review.day_status(plan, [], has_cross=True, is_future=False) == "cross_only"


def test_day_status_skipped_injury():
    plan = {"type": "tempo", "distance_km": 10.0}
    assert review.day_status(plan, [], injured=True, is_future=False) == "skipped_injury"


# ── week_overview shape ───────────────────────────────────────────────────────

def test_week_overview_has_7_days():
    # Plan: Mon easy, Wed tempo, Sat long; rest of days have no plan
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    # Log: Mon done, Wed done
    log_spec = [(0, "easy", 8.1), (2, "tempo", 9.9)]
    home, this_monday = _make_home_with_week(plan_spec, log_spec)

    ov = review.week_overview(home, 0)
    assert len(ov["days"]) == 7
    assert ov["has_plan"] is True
    assert ov["start"] == this_monday.isoformat()


def test_week_overview_day_statuses():
    today = local_today()
    this_monday = _monday_of(today)

    # Build a plan for Mon (done), Wed (done), Fri (upcoming if future, else skipped/done),
    # Sun long (upcoming or done depending on today).
    # Use only Mon and Wed to avoid date-relative flakiness on Fri/Sun.
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    log_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    ov = review.week_overview(home, 0)
    days_by_dow = {d["dow"]: d for d in ov["days"]}

    assert days_by_dow["Mon"]["status"] == "done"
    assert days_by_dow["Wed"]["status"] == "done"


def test_week_overview_no_plan():
    home, _ = _make_home_with_week(plan_days_spec=None, log_entries=[(0, "easy", 8.0)])
    ov = review.week_overview(home, 0)
    assert ov["has_plan"] is False
    assert len(ov["days"]) == 7
    # Mon has an unplanned run
    mon = next(d for d in ov["days"] if d["dow"] == "Mon")
    assert mon["status"] == "unplanned"


# ── week_review_aggregate ─────────────────────────────────────────────────────

def test_week_review_aggregate_adherence_pct():
    # 3 planned sessions, 2 done → 67%
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    log_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    assert agg["planned_sessions"] == 3
    assert agg["completed_sessions"] == 2
    assert agg["adherence_pct"] == 67


def test_week_review_aggregate_volume():
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    log_spec = [(0, "easy", 8.5), (2, "tempo", 9.5)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    assert agg["planned_km"] == 38.0
    assert abs(agg["actual_km"] - 18.0) < 0.01


def test_week_review_aggregate_key_sessions():
    # tempo + long are key types; easy is not
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    log_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]  # long not done
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    assert agg["key_planned"] == 2   # tempo + long
    assert agg["key_done"] == 1      # only tempo done


def test_week_review_aggregate_shape():
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    log_spec = [(0, "easy", 8.0)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    # Required keys
    for key in ("offset", "start", "end", "has_plan", "planned_sessions",
                "completed_sessions", "adherence_pct", "days_brief",
                "goal", "injury", "metrics"):
        assert key in agg, f"missing key: {key}"


# ── week_review_status ────────────────────────────────────────────────────────

def test_week_review_status_not_ready_mid_week():
    # Plan only Mon (in the past if today >= Mon+1) but long Saturday (future)
    today = local_today()
    this_monday = _monday_of(today)

    # Put the only planned session on Saturday (future unless today is Sun)
    saturday = this_monday + _dt.timedelta(days=5)
    is_sat_future = saturday.isoformat() >= today.isoformat()

    plan_spec = [(5, "long", 20.0)]  # Saturday
    if is_sat_future:
        # Saturday not yet run → not ready
        home, _ = _make_home_with_week(plan_spec, log_entries=[])
        st = review.week_review_status(home, 0)
        assert st["ready"] is False
    else:
        # Saturday is past but no run → skipped → not ready
        home, _ = _make_home_with_week(plan_spec, log_entries=[])
        st = review.week_review_status(home, 0)
        assert st["ready"] is False


def test_week_review_status_has_plan_field():
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    home, _ = _make_home_with_week(plan_spec, log_entries=[])
    st = review.week_review_status(home, 0)
    assert st["has_plan"] is True
    assert "planned_sessions" in st
    assert "ready" in st


def test_week_review_status_no_plan_is_not_ready():
    home, _ = _make_home_with_week(plan_days_spec=None, log_entries=[(0, "easy", 8.0)])
    st = review.week_review_status(home, 0)
    assert st["has_plan"] is False
    assert st["ready"] is False


# ── week_review_prompt: no-prescription invariant ────────────────────────────

def test_week_review_prompt_contains_no_prescription_rule():
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    log_spec = [(0, "easy", 8.0), (2, "tempo", 10.0)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    prompt = review.week_review_prompt(home, agg)
    assert "특정 세션을 처방하지 마" in prompt, \
        "no-prescription rule string must appear in week_review_prompt"


# ── format_week_summary ───────────────────────────────────────────────────────

def test_format_week_summary_contains_volume():
    plan_spec = [(0, "easy", 8.0), (2, "tempo", 10.0), (5, "long", 20.0)]
    log_spec = [(0, "easy", 8.5), (2, "tempo", 9.5)]
    home, _ = _make_home_with_week(plan_spec, log_spec)

    agg = review.week_review_aggregate(home, 0)
    summary = review.format_week_summary(agg)
    assert "볼륨" in summary
    assert "38.0" in summary  # planned_km


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
    print(f"\nreview: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
