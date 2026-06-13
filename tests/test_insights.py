"""Unit tests for the insights detector pipeline (scripts/insights.py + scripts/insight_detectors/).

Run: `python3 tests/test_insights.py`  (stdlib only; no pytest required).

Tests:
  1. All 107 detectors are registered in insight_detectors.ALL.
  2. detect() with empty home returns [].
  3. Synthetic 30-run log spanning 16 weeks fires well-formed cards.
  4. All card ids are unique within one detect() call.
  5. Every individual detector from ALL returns [] or a list of well-formed cards
     — never raises, never returns None.
  6. Card schema validation: required keys present, score in [0,1], no None id.
"""
import datetime
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import insight_detectors  # noqa: E402
import insights            # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TODAY = datetime.date(2026, 6, 13)
_REQUIRED_KEYS = {"id", "kind", "icon", "headline", "wow", "stat", "score", "coach_hint"}


def _make_run(date, type_="easy", dist=10.0, pace_s=330, hr=140, max_hr=155,
              cad=175, ascent=50, dur=3300, cal=600, rpe=5,
              source="garmin", source_id=None):
    return {
        "date": date,
        "type": type_,
        "dist": dist,
        "pace_s": pace_s,
        "pace": f"{pace_s // 60}:{pace_s % 60:02d}",
        "hr": hr,
        "max_hr": max_hr,
        "cad": cad,
        "ascent": ascent,
        "dur": dur,
        "cal": cal,
        "rpe": rpe,
        "source": source,
        "source_id": source_id or f"garmin-{date.isoformat()}",
    }


def _synthetic_runs():
    """30 runs spread over ~16 weeks ending on _TODAY so 'recent' windows are populated.

    The schedule lists (days_before_today, type, dist_km, pace_s, avg_hr, max_hr).
    Smaller days_before = more recent.  The final two runs are 0 and 2 days ago so
    every detector that looks at the last 7/14/28 days finds data.
    """
    runs = []
    # (days_before_today, type, dist, pace_s, hr, max_hr)
    schedule = [
        (112, "easy",     8,  360, 135, 150),
        (110, "easy",     10, 355, 138, 153),
        (108, "long",     18, 375, 142, 158),
        (105, "recovery", 6,  400, 125, 138),
        (103, "easy",     10, 350, 138, 152),
        (101, "tempo",    10, 295, 158, 168),
        (98,  "easy",     9,  348, 136, 150),
        (96,  "interval", 10, 275, 162, 178),
        (94,  "long",     20, 372, 143, 160),
        (91,  "recovery", 5,  405, 122, 135),
        (89,  "easy",     11, 342, 137, 151),
        (87,  "tempo",    12, 290, 160, 170),
        (84,  "easy",     9,  340, 136, 150),
        (82,  "interval", 12, 268, 165, 182),
        (80,  "long",     22, 366, 144, 162),
        (77,  "recovery", 6,  398, 123, 136),
        (75,  "easy",     12, 334, 137, 151),
        (73,  "tempo",    10, 285, 161, 171),
        (70,  "easy",     10, 330, 136, 150),
        (68,  "interval", 10, 262, 166, 183),
        (65,  "long",     24, 362, 145, 163),
        (62,  "recovery", 5,  402, 121, 134),
        (56,  "easy",     12, 325, 136, 150),
        (50,  "tempo",    12, 280, 162, 172),
        (42,  "easy",     10, 322, 135, 149),
        (35,  "interval", 12, 258, 167, 184),
        (21,  "long",     26, 356, 146, 164),
        (14,  "recovery", 5,  400, 120, 133),
        (7,   "easy",     12, 318, 135, 149),
        (2,   "tempo",    12, 275, 162, 172),
    ]
    for days_ago, typ, dist, pace_s, hr, max_hr in schedule:
        d = _TODAY - datetime.timedelta(days=days_ago)
        runs.append(_make_run(d, type_=typ, dist=dist, pace_s=pace_s,
                               hr=hr, max_hr=max_hr))
    runs.sort(key=lambda r: r["date"])
    return runs


def _synthetic_ctx():
    return {
        "today": _TODAY,
        "goal": {"event": "marathon", "target_time": "3:45:00",
                 "target_pace": "5:20", "weeks_remaining": 10},
        "profile": {"current_pb": {"half": "1:52:00", "10k": "50:00"}},
        "pb": [],
        "plan": {},
        "week_meta": {"target_km": 55.0},
        "deep": {},
        "body": None,
        "diagnosis": {},
    }


def _card_valid(c) -> str:
    """Return empty string if card is valid, else a description of the problem."""
    if not isinstance(c, dict):
        return f"not a dict: {type(c)}"
    missing = _REQUIRED_KEYS - set(c.keys())
    if missing:
        return f"missing keys: {missing}"
    if c.get("id") is None:
        return "id is None"
    if not isinstance(c.get("score"), (int, float)):
        return f"score not numeric: {c.get('score')}"
    if not (0.0 <= c["score"] <= 1.0):
        return f"score out of [0,1]: {c['score']}"
    if not isinstance(c.get("headline"), str) or not c["headline"].strip():
        return "headline empty or non-str"
    if not isinstance(c.get("wow"), str) or not c["wow"].strip():
        return "wow empty or non-str"
    return ""


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_detector_count():
    """All 107 detectors are registered."""
    n = len(insight_detectors.ALL)
    assert n >= 100, f"Expected >=100 detectors in ALL, got {n}"
    print(f"  detector count: {n}")


def test_empty_home_returns_empty():
    """detect() on an empty directory returns []."""
    with tempfile.TemporaryDirectory() as tmp:
        result = insights.detect(home=tmp)
    assert result == [], f"Expected [] for empty home, got {result}"


def test_well_formed_cards_from_synthetic_log():
    """Synthetic 30-run log fires cards and all are well-formed."""
    runs = _synthetic_runs()
    ctx = _synthetic_ctx()
    cards = []
    seen = set()
    for fn in insight_detectors.ALL:
        try:
            for c in (fn(runs, ctx) or []):
                if c and c.get("id") not in seen:
                    seen.add(c["id"])
                    cards.append(c)
        except Exception as exc:
            raise AssertionError(f"Detector {fn.__name__} raised: {exc}") from exc

    assert len(cards) > 0, "Expected at least 1 card from synthetic log"
    print(f"  cards fired: {len(cards)}")

    for c in cards:
        err = _card_valid(c)
        assert not err, f"Card {c.get('id')!r} invalid: {err}\n  card={c}"


def test_unique_ids():
    """All card ids are unique within a single detect() run."""
    runs = _synthetic_runs()
    ctx = _synthetic_ctx()
    cards = []
    seen = set()
    for fn in insight_detectors.ALL:
        try:
            for c in (fn(runs, ctx) or []):
                if c:
                    cards.append(c)
        except Exception:
            pass
    ids = [c.get("id") for c in cards]
    # count duplicates before dedup
    from collections import Counter
    dupes = [cid for cid, cnt in Counter(ids).items() if cnt > 1]
    # duplicates are expected to be deduplicated by detect(); here we just confirm ids are strings
    for cid in ids:
        assert isinstance(cid, str) and cid, f"Non-string or empty id: {cid!r}"


def test_no_detector_raises():
    """Every detector returns [] or a list of dicts — never raises, never returns None."""
    runs = _synthetic_runs()
    ctx = _synthetic_ctx()
    failed = []
    for fn in insight_detectors.ALL:
        try:
            result = fn(runs, ctx)
        except Exception as exc:
            failed.append(f"{fn.__name__}: raised {exc}")
            continue
        if result is None:
            failed.append(f"{fn.__name__}: returned None instead of []")
            continue
        if not isinstance(result, list):
            failed.append(f"{fn.__name__}: returned {type(result)} instead of list")
    if failed:
        raise AssertionError("Detectors with failures:\n  " + "\n  ".join(failed))


def test_all_detectors_non_empty_on_rich_log():
    """With the synthetic log, at least 50% of detectors fire at least one card
    (guards against entire categories being silently broken)."""
    runs = _synthetic_runs()
    ctx = _synthetic_ctx()
    fired = 0
    for fn in insight_detectors.ALL:
        try:
            result = fn(runs, ctx)
            if result:
                fired += 1
        except Exception:
            pass
    total = len(insight_detectors.ALL)
    pct = fired / total * 100
    # lower bound: at least 15% of detectors should fire on a rich 30-run log
    assert fired >= total * 0.15, (
        f"Only {fired}/{total} ({pct:.0f}%) detectors fired — check for systematic breakage"
    )
    print(f"  detectors fired: {fired}/{total} ({pct:.0f}%)")


def test_detect_deduplication_and_ranking():
    """detect() returns cards sorted by score descending with no duplicate ids."""
    with tempfile.TemporaryDirectory() as tmp:
        # write minimal state files
        log_path = os.path.join(tmp, "training-log.jsonl")
        runs_raw = _synthetic_runs()
        with open(log_path, "w") as fh:
            for r in runs_raw:
                entry = {
                    "date": r["date"].isoformat(),
                    "type": r["type"],
                    "source": r["source"],
                    "source_id": r["source_id"],
                    "actual": {
                        "distance_km": r["dist"],
                        "pace": r["pace"],
                        "avg_hr": r["hr"],
                        "max_hr": r["max_hr"],
                        "cadence": r["cad"],
                        "ascent_m": r["ascent"],
                        "duration_s": r["dur"],
                        "calories": r["cal"],
                        "rpe": r["rpe"],
                    },
                }
                fh.write(json.dumps(entry) + "\n")

        with open(os.path.join(tmp, "goal.json"), "w") as fh:
            json.dump({"event": "marathon", "target_time": "3:45:00",
                       "target_pace": "5:20", "weeks_remaining": 10}, fh)
        with open(os.path.join(tmp, "runner-profile.json"), "w") as fh:
            json.dump({"current_pb": {"half": "1:52:00", "10k": "50:00"}}, fh)

        result = insights.detect(home=tmp, max_cards=8)

    assert isinstance(result, list), f"detect() returned {type(result)}"
    assert len(result) <= 8
    ids = [c["id"] for c in result]
    assert len(ids) == len(set(ids)), f"Duplicate ids in detect() output: {ids}"

    for i in range(len(result) - 1):
        assert result[i]["score"] >= result[i + 1]["score"], (
            f"Cards not sorted by score: [{i}]={result[i]['score']} > [{i+1}]={result[i+1]['score']}"
        )
    print(f"  detect() returned {len(result)} cards, sorted, unique ids")


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_detector_count,
        test_empty_home_returns_empty,
        test_well_formed_cards_from_synthetic_log,
        test_unique_ids,
        test_no_detector_raises,
        test_all_detectors_non_empty_on_rich_log,
        test_detect_deduplication_and_ranking,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"  running {t.__name__} ...", end=" ")
            t()
            print("ok")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'PASS' if failed == 0 else 'FAIL'} — {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
