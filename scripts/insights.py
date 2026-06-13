"""Training insights — the "와우 모먼트" detector pipeline.

Strava/Garmin/Coros show per-activity stats and a fitness number. What they DON'T do is
surface *cross-activity* trends, self-relative records, and hidden patterns with an
explanation. This module loads every available prod signal (full training-log + goal +
profile + plan + PB + a few deep-analyzed recent runs) into a ``ctx``, runs the detector
registry (``insight_detectors``) deterministically, and returns score-ranked cards. The UI
shows the top few; the rest stay a latent pool.

Pure + defensive: ``detect`` never raises (each detector is guarded), and ``_build_ctx``
degrades gracefully when a file is missing.

Plugin usage:
    python3 scripts/insights.py [--home PATH] [--top N] [--all] [--json]
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from typing import List, Optional

# ---------------------------------------------------------------------------
# sys.path bootstrap — allow running as ``python3 scripts/insights.py`` directly
# ---------------------------------------------------------------------------
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from logquery import load_log, is_run, pace_sec          # noqa: E402
from ompb_env import resolve_home, local_today           # noqa: E402
import insight_detectors                                  # noqa: E402

# Optional sibling modules — imported lazily so the module is importable even when
# review / body are absent (degrades gracefully to empty ctx fields).
def _try_import(name):
    try:
        return __import__(name)
    except ImportError:
        return None

# how many recent deep-analyzable runs to pull lap/zone/decoupling signals for (bounded — each
# is an analyze call; deep detectors no-op when ``ctx['deep']`` is empty).
_DEEP_RECENT = 4


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _runs(home: str) -> List[dict]:
    """Normalized, date-sorted running entries with parsed pace seconds."""
    out: List[dict] = []
    for r in load_log(home):
        if not is_run(r):
            continue
        try:
            day = _dt.date.fromisoformat(str(r.get("date")))
        except (ValueError, TypeError):
            continue
        a = r.get("actual") or {}
        out.append({
            "date": day,
            "type": r.get("type") or "easy",
            "dist": a.get("distance_km"),
            "pace_s": pace_sec(a.get("pace")),
            "pace": a.get("pace"),
            "hr": a.get("avg_hr"),
            "max_hr": a.get("max_hr"),
            "cad": a.get("cadence"),
            "ascent": a.get("ascent_m"),
            "dur": a.get("duration_s"),
            "cal": a.get("calories"),
            "rpe": a.get("rpe"),
            "source": r.get("source"),
            "source_id": r.get("source_id"),
        })
    out.sort(key=lambda x: x["date"])
    return out


def _read(home: str, name: str):
    path = os.path.join(home, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _deep_recent(home: str, runs: List[dict], analyze_fn=None) -> dict:
    """analyze_activity for the few most-recent deep-analyzable runs (Strava + HR). Best-effort:
    any failure is skipped so the instant path never breaks. Enables zone/decoupling/lap detectors.

    ``analyze_fn(source_id, home) -> dict | None`` is injected by the caller; when None, deep
    analysis is skipped (detectors that need it simply return []).
    """
    if analyze_fn is None:
        return {}
    deep: dict = {}
    cand = [r for r in reversed(runs)
            if str(r.get("source_id") or "").startswith("strava") and r.get("hr")]
    for r in cand[:_DEEP_RECENT]:
        sid = r["source_id"]
        try:
            a = analyze_fn(sid, home)
            if a:
                deep[sid] = a
        except Exception:
            continue
    return deep


def _build_ctx(home: str, runs: List[dict], today: _dt.date, analyze_fn=None) -> dict:
    """Assemble every available signal source into the detector context. Missing files → {}."""
    plan = _read(home, "plan-week.json") or {}

    # week_meta from review.week_overview if available
    week_meta: dict = {}
    review_mod = _try_import("review")
    if review_mod is not None:
        try:
            week_meta = (review_mod.week_overview(home, 0) or {}).get("week_meta") or {}
        except Exception:
            week_meta = {}

    # body summary if available
    body_data = None
    body_mod = _try_import("body")
    if body_mod is not None:
        try:
            body_data = body_mod.summary(home)
        except Exception:
            body_data = None

    pbh = _read(home, "pb-history.json") or {}
    return {
        "today": today,
        "goal": _read(home, "goal.json") or {},
        "profile": _read(home, "runner-profile.json") or {},
        "diagnosis": _read(home, "diagnosis.json") or {},
        "pb": pbh.get("entries") or [],
        "plan": plan,
        "week_meta": week_meta,
        "deep": _deep_recent(home, runs, analyze_fn),
        "body": body_data,
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def detect(
    home: Optional[str] = None,
    *,
    max_cards: int = 8,
    analyze_fn=None,
) -> List[dict]:
    """Scan every signal → score-ranked insight cards (highest first). Deterministic; never raises.

    Args:
        home: OMPB home directory (resolved via resolve_home when None).
        max_cards: how many top-scored cards to return.
        analyze_fn: optional ``(source_id, home) -> dict`` callback for deep activity analysis.
                    When None, deep detectors (zone/decoupling/lap signals) silently return [].
    """
    home = resolve_home(home)
    runs = _runs(home)
    if len(runs) < 8:
        return []
    today = local_today()
    ctx = _build_ctx(home, runs, today, analyze_fn=analyze_fn)
    cards: List[dict] = []
    seen: set = set()
    for fn in insight_detectors.ALL:
        try:
            for c in (fn(runs, ctx) or []):
                if not c or c.get("id") in seen:
                    continue
                seen.add(c["id"])
                cards.append(c)
        except Exception:
            continue
    cards.sort(key=lambda c: -c.get("score", 0.0))
    return cards[:max_cards]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="insights",
        description="Run the 와우 모먼트 insight detector pipeline and print ranked cards.",
    )
    parser.add_argument("--home", default=None, help="OMPB home directory (default: auto-resolve)")
    parser.add_argument("--top", type=int, default=8, help="Number of top cards to show (default 8)")
    parser.add_argument("--all", dest="show_all", action="store_true",
                        help="Show all detected cards (ignores --top)")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Output raw JSON array instead of formatted text")
    args = parser.parse_args()

    home = resolve_home(args.home)
    runs = _runs(home)
    if len(runs) < 8:
        print(f"Not enough runs (found {len(runs)}, need >=8). Import more data first.")
        return

    today = local_today()
    ctx = _build_ctx(home, runs, today, analyze_fn=None)
    cards: List[dict] = []
    seen: set = set()
    for fn in insight_detectors.ALL:
        try:
            for c in (fn(runs, ctx) or []):
                if not c or c.get("id") in seen:
                    continue
                seen.add(c["id"])
                cards.append(c)
        except Exception:
            continue
    cards.sort(key=lambda c: -c.get("score", 0.0))

    limit = None if args.show_all else args.top
    output = cards if limit is None else cards[:limit]

    if args.as_json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return

    print(f"\n{'─'*60}")
    print(f"  insight detectors: {len(insight_detectors.ALL)} detectors, "
          f"{len(cards)} cards fired, showing {'all' if limit is None else limit}")
    print(f"  home: {home}  |  runs: {len(runs)}  |  today: {today}")
    print(f"{'─'*60}")
    for i, c in enumerate(output, 1):
        score = c.get("score", 0.0)
        kind = c.get("kind", "")
        icon = c.get("icon", "")
        headline = c.get("headline", "")
        print(f"  {i:2d}. [{score:.2f}] {icon} {headline}  ({kind})")
        wow = c.get("wow", "")
        if wow:
            # wrap at ~72 chars for readability
            words = wow.split()
            line = "      "
            for w in words:
                if len(line) + len(w) + 1 > 76:
                    print(line)
                    line = "      " + w
                else:
                    line += (" " if line.strip() else "") + w
            if line.strip():
                print(line)
        print()
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    _cli()
