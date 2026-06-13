"""Shared contract + helpers for insight detectors.

DETECTOR CONTRACT
-----------------
A detector is ``def detector(runs, ctx) -> list[card]``:

- ``runs``  : date-sorted list of normalized run dicts. Each run:
    {date: datetime.date, type: str(easy|recovery|long|tempo|interval|cross?),
     dist: float|None (km), pace_s: int|None (sec/km), pace: str|None ('M:SS'),
     hr: int|None (avg), max_hr: int|None, cad: int|None, ascent: float|None (m),
     dur: int|None (sec), cal: int|None, rpe: int|None, source: str, source_id: str}
- ``ctx``   : {
     today: datetime.date,                  # KST "today"
     goal: dict,      # goal.json (event, target_time, target_pace, race_date, weeks_remaining, ...)
     profile: dict,   # runner-profile.json (experience, weekly_mileage_km, current_pb{...})
     pb: list,        # pb-history entries [{event, time, date}]
     plan: dict,      # plan-week.json (days, week, coach_notes)
     week_meta: dict, # {phase, focus, target_km, ramp_pct, prev_week_km, coach_notes}
     deep: dict,      # {source_id: analyze_activity(...)}  for a few recent deep runs (may be {})
   }

A detector returns 0+ cards. NEVER raise (the registry guards, but be defensive). Card schema:
    {id: str(unique), kind: 'improvement'|'pr'|'warning'|'consistency'|'adaptation',
     icon: str(emoji), headline: str(number-forward, short), wow: str(one-line meaning),
     stat: dict(supporting numbers), score: float(0..1), coach_hint: str(seed for tap-narration)}

Keep detectors deterministic and self-relative. Only surface a card when the signal clears a
meaningful threshold (the UI shows the top-scoring few). Use textContent-safe plain strings.
"""
from __future__ import annotations

import statistics as _st
from typing import List, Optional


def fmt_pace(sec) -> str:
    """Seconds-per-km → 'M:SS'."""
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def age(run, today) -> int:
    """Days since the run (>=0)."""
    return (today - run["date"]).days


def window(runs: List[dict], today, lo: int, hi: int) -> List[dict]:
    """Runs with ``lo < days_ago <= hi``."""
    return [r for r in runs if lo < (today - r["date"]).days <= hi]


def mean(vals) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return _st.mean(vals) if vals else None


def median(vals) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return _st.median(vals) if vals else None


def has(run, *fields) -> bool:
    """True if every field on the run is present (non-None)."""
    return all(run.get(f) is not None for f in fields)


def card(id, kind, icon, headline, wow, stat, score, coach_hint) -> dict:
    """Build a card dict in the canonical shape (clamps score to 0..1)."""
    return {"id": id, "kind": kind, "icon": icon, "headline": headline, "wow": wow,
            "stat": stat or {}, "score": max(0.0, min(1.0, float(score))), "coach_hint": coach_hint}
