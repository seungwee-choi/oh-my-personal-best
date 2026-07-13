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
  progression — laps get near-monotonically faster through the run (asserted from lap
                structure by analyze_laps, not derivable from session aggregates here)
  long      — distance ≥ the long-run threshold (endurance, kept distance-first)

Honest limits: from *session aggregates* (no per-lap data) tempo↔interval can't be
perfect — we use the avg→max HR spread as the discriminator (intervals swing, tempo
holds). Calibration is HR-max-anchored (%HRmax), falling back to pace-only or 'easy'
when HR is absent. ``race`` is never auto-inferred (needs a name/flag); ``cross``/
``rest`` are out of scope here.

Pace sanity guard: HR can spike from heat, hills, cardiac drift, or stop-and-go
running, so a single peak with a big avg→max swing isn't enough to call a session a
workout. A real tempo/interval is never slower, on session average, than this runner's
easy-slow pace — so the quality labels are withheld when the average pace is slower
than that band (and pace data exists). That combination is a fatigued/terrain easy run,
not a workout; without the guard one HR spike on an 18 km easy run mislabels it interval
and blurs the intensity distribution.
"""
from __future__ import annotations

from typing import Dict, List, Optional

RUN_TYPES = ("easy", "long", "tempo", "interval", "recovery", "progression")

# Activity-name / title keywords → type. Highest-confidence signal (the runner named it).
# Ordered: a race word wins over "long", "interval" over "tempo", etc. Shared by the CSV
# and Strava importers so naming inference stays consistent.
_NAME_KEYWORDS = [
    ("race",     ["race", "competition", "parkrun", "대회", "레이스", "마라톤 대회"]),
    ("interval", ["interval", "track", "speed", "vo2", "repeat", "fartlek",
                  "인터벌", "트랙", "스피드", "반복"]),
    ("tempo",    ["tempo", "threshold", "lactate", "cruise", "템포", "역치", "임계"]),
    ("progression", ["progression", "progressive", "build up", "buildup", "build-up",
                     "프로그레션", "빌드업", "점증"]),
    ("long",     ["long run", "longrun", "long", "lsd", "endurance", "롱런", "롱 런", "장거리"]),
    ("recovery", ["recovery", "shake out", "shakeout", "regeneration", "regen", "jog",
                  "회복", "리커버리", "조깅"]),
]


def name_to_type(text: Optional[str]) -> Optional[str]:
    """Infer a run type from an activity name/title, or None if no keyword matches."""
    if not text:
        return None
    low = text.lower()
    for session_type, keywords in _NAME_KEYWORDS:
        if any(kw in low for kw in keywords):
            return session_type
    return None


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

    # Pace sanity guard for the quality labels (interval/tempo): an HR peak can come from
    # heat, hills, drift, or stop-and-go running, so we refuse a workout label when the
    # session's average pace is slower than this runner's easy-slow band. A genuine
    # tempo/interval (even with recovery jogs averaged in) never runs that slow. When pace
    # is unknown we can't check, so the guard stays off and HR alone decides as before.
    quality_pace_ok = not (pace is not None and ref.get("easy_slow") and pace > ref["easy_slow"])

    # Endurance is distance-first (a marathon-pace long run is still a long run).
    if distance_km is not None and distance_km >= long_km:
        return "long"

    # Interval: a high peak with a big avg→max swing (repeats with recovery between),
    # confirmed by a pace fast enough to be real work.
    if (ref.get("hard_hr") and ref.get("spread_interval")
            and mx and avg and mx >= ref["hard_hr"] and spread is not None
            and spread >= ref["spread_interval"] and quality_pace_ok):
        return "interval"

    # Tempo: sustained high HR held steady (small spread) — threshold / cruise.
    if (ref.get("tempo_hr") and avg and avg >= ref["tempo_hr"]
            and (spread is None or spread <= ref.get("spread_steady", 1e9))
            and quality_pace_ok):
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
