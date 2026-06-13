"""Unit tests for injury tracking & the return-to-run ladder (scripts/injury.py).

Run: `python3 tests/test_injury.py`  (stdlib only; no pytest required).
"""
import datetime as _dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import injury  # noqa: E402


def _home():
    return tempfile.mkdtemp(prefix="ompb_inj_")


# ── parse_mention: PROPOSE only when a part token co-occurs with a pain cue ──────
def test_parse_requires_part_and_pain():
    assert injury.parse_mention("오늘 날씨 좋다") is None          # no part, no pain
    assert injury.parse_mention("무릎 보호대 샀어") is None         # part but no pain cue
    p = injury.parse_mention("왼쪽 무릎이 아파")
    assert p and p["body_part"] == "knee" and p["side"] == "left"


def test_parse_longest_first_part():
    # 족저근막/발바닥 must beat the generic 발
    p = injury.parse_mention("발바닥이 시큰거려")
    assert p["body_part"] == "plantar"


def test_parse_severity_and_onset():
    today = _dt.date(2026, 6, 13)
    p = injury.parse_mention("오른쪽 아킬레스 3일째 심하게 아파", today=today)
    assert p["body_part"] == "achilles" and p["side"] == "right"
    assert p["severity"] == 7                       # "심하게"
    assert p["onset_date"] == "2026-06-11"          # 3일째 → today-2


# ── phase ladder ─────────────────────────────────────────────────────────────────
def test_phase_ladder_order():
    assert injury.next_phase("rest") == "walk"
    assert injury.next_phase("full") == "full"      # clamps
    assert injury.prev_phase("rest") == "rest"      # clamps
    assert injury.phase_meta("rest")["load_cap_pct"] == 0
    assert injury.phase_meta("full")["allowed"] is None


def test_default_phase_from_severity():
    assert injury._default_phase(9) == "rest"
    assert injury._default_phase(5) == "walk_run"
    assert injury._default_phase(None) == "easy_only"


def test_advance_decision_streak_and_flare():
    ok = {"ran": True, "pain_during": 1, "pain_after": 0}
    # two consecutive pain-free running check-ins → advance
    assert injury.advance_decision("easy_only", [ok, ok]) == "build"
    # a flare steps back
    flare = {"ran": True, "pain_during": 7, "pain_after": 2}
    assert injury.advance_decision("build", [ok, flare]) == "easy_only"
    # a single ok check-in is not enough
    assert injury.advance_decision("easy_only", [ok]) == "easy_only"


# ── persistence + snapshot ─────────────────────────────────────────────────────
def test_create_and_snapshot():
    home = _home()
    assert injury.snapshot(home)["active"] is False
    ep = injury.create_episode(home, {"body_part": "knee", "side": "left", "severity": 5})
    snap = injury.snapshot(home)
    assert snap["active"] and snap["mode"] == "recovery"
    assert snap["load_cap_pct"] == injury.phase_meta(ep["phase"])["load_cap_pct"]
    assert "easy" in (snap["allowed_types"] or []) or snap["allowed_types"] is not None


def test_concurrent_injuries_combine_to_most_restrictive():
    home = _home()
    injury.create_episode(home, {"body_part": "knee", "phase": "build"})       # cap 80
    injury.create_episode(home, {"body_part": "achilles", "phase": "walk_run"})  # cap 30
    snap = injury.snapshot(home)
    assert snap["load_cap_pct"] == 30          # the lowest cap binds
    # allowed = intersection of build & walk_run allowed sets
    assert set(snap["allowed_types"]) == {"recovery", "rest", "cross"}


def test_checkin_advances_and_resolve():
    home = _home()
    ep = injury.create_episode(home, {"body_part": "calf", "phase": "easy_only"})
    injury.checkin(home, ep["id"], pain_during=1, pain_after=0, ran=True)
    out = injury.checkin(home, ep["id"], pain_during=0, pain_after=0, ran=True)
    assert out["phase"] == "build"             # two clean check-ins advanced one phase
    resolved = injury.resolve(home, ep["id"])
    assert resolved["status"] == "resolved" and resolved["phase"] == "full"
    assert injury.snapshot(home)["active"] is False


def test_injured_dates_span():
    home = _home()
    injury.create_episode(home, {"body_part": "knee", "onset_date": "2026-06-01",
                                 "phase": "easy_only"})
    injury.resolve(home, injury.active(home)["id"], date="2026-06-03")
    dates = injury.injured_dates(home, "2026-06-01", "2026-06-30")
    assert dates == {"2026-06-01", "2026-06-02", "2026-06-03"}


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
    print(f"\ninjury: {passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
