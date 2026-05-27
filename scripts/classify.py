#!/usr/bin/env python3
"""classify.py — refine a running session's training type from its own metrics,
calibrated to the runner (standard library only).

Device imports can only see distance, so they type every run easy/long. But a coach
reads intensity *relative to this runner*: 159 bpm is "hard" for one athlete and
"easy" for another. So we calibrate HR (and pace) bands from the runner's whole log,
then label each run against those bands:

  recovery  — very low HR, slow, short (true regeneration)
  easy      — aerobic base (the default)
  tempo     — sustained high HR with a steady effort (threshold / cruise)
  interval  — high peak HR with a big HR spread (repeats / surges with recovery)
  long      — distance ≥ the long-run threshold (endurance, kept distance-first)

Honest limits: from *session aggregates* (no per-lap data) tempo↔interval can't be
perfect — we use the avg→max HR spread as the discriminator (intervals swing, tempo
holds). Calibration is HR-max-anchored (%HRmax), falling back to pace-only or 'easy'
when HR is absent. ``race`` is never auto-inferred (needs a name/flag); ``cross``/
``rest`` are out of scope here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

RUN_TYPES = ("easy", "long", "tempo", "interval", "recovery")


def _pace_to_sec(p) -> Optional[int]:
    if not p or ":" not in str(p):
        return None
    try:
        m, s = str(p).split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return None


def _pct(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(q * (len(s) - 1) + 0.5)))
    return s[i]


def calibrate(entries: List[dict]) -> Dict:
    """Derive this runner's intensity bands from their running log.

    HR bands are anchored to an estimated HRmax (99th-pct of session max HR, so one
    spike doesn't skew it); pace bands from the run-pace distribution. Returns whatever
    can be derived — ``refine`` degrades gracefully when a band is missing.
    """
    avg_hrs, max_hrs, paces = [], [], []
    for e in entries:
        if e.get("sport") and e["sport"] != "running":
            continue
        a = e.get("actual") or {}
        if a.get("avg_hr"):
            avg_hrs.append(a["avg_hr"])
        if a.get("max_hr"):
            max_hrs.append(a["max_hr"])
        ps = _pace_to_sec(a.get("pace"))
        if ps:
            paces.append(ps)

    ref: Dict = {"has_hr": bool(avg_hrs), "has_pace": bool(paces)}

    hrmax = _pct(max_hrs, 0.99) or (max(avg_hrs) * 1.10 if avg_hrs else None)
    if hrmax:
        ref["hrmax"] = round(hrmax)
        # Recovery is bounded by BOTH physiology (72% HRmax) and this runner's own easy
        # distribution (P25 of avg HR), whichever is lower — so a low-HR runner whose
        # normal easy sits at ~72% doesn't get half their easy pile mislabeled recovery.
        p25 = _pct(avg_hrs, 0.25)
        ref["recovery_hr"] = min(0.72 * hrmax, p25) if p25 else 0.72 * hrmax
        ref["tempo_hr"] = 0.84 * hrmax       # avg ≥ this → tempo candidate
        ref["hard_hr"] = 0.89 * hrmax        # max ≥ this → interval-capable
        ref["spread_interval"] = 0.13 * hrmax  # avg→max swing that signals repeats
        ref["spread_steady"] = 0.07 * hrmax    # spread ≤ this → a held (steady) effort
    if paces:
        ref["fast_pace"] = _pct(paces, 0.20)   # quickest fifth of runs
        ref["easy_slow"] = _pct(paces, 0.72)   # slowest ~quarter → recovery-slow
    return ref


def refine(actual: Optional[dict], distance_km: Optional[float], ref: Dict,
           long_km: float = 19.0) -> str:
    """Return a refined run type for one session given its metrics and the runner's
    calibrated ``ref`` bands (from ``calibrate``; pass ``{}`` for HR/pace-only defaults)."""
    a = actual or {}
    avg = a.get("avg_hr")
    mx = a.get("max_hr")
    pace = _pace_to_sec(a.get("pace"))
    spread = (mx - avg) if (mx and avg) else None

    # Endurance is distance-first (a marathon-pace long run is still a long run).
    if distance_km is not None and distance_km >= long_km:
        return "long"

    # Interval: a high peak with a big avg→max swing (repeats with recovery between).
    if (ref.get("hard_hr") and ref.get("spread_interval")
            and mx and avg and mx >= ref["hard_hr"] and spread is not None
            and spread >= ref["spread_interval"]):
        return "interval"

    # Tempo: sustained high HR held steady (small spread) — threshold / cruise.
    if (ref.get("tempo_hr") and avg and avg >= ref["tempo_hr"]
            and (spread is None or spread <= ref.get("spread_steady", 1e9))):
        return "tempo"

    # Recovery: genuinely low HR, slow, AND short (regeneration — not just any easy run,
    # which for a low-HR runner would otherwise swallow the whole easy pile).
    dur = a.get("duration_s")
    is_short = (distance_km is not None and distance_km <= 7.0) or (dur is not None and dur <= 2700)
    if (ref.get("recovery_hr") and avg and avg <= ref["recovery_hr"] and is_short
            and (pace is None or not ref.get("easy_slow") or pace >= ref["easy_slow"])):
        return "recovery"

    # No HR? lean on pace alone.
    if avg is None and pace is not None:
        if ref.get("fast_pace") and pace <= ref["fast_pace"]:
            return "tempo"
        if ref.get("easy_slow") and pace >= ref["easy_slow"] + 30:
            return "recovery"

    return "easy"
