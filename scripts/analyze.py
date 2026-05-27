#!/usr/bin/env python3
"""analyze.py — single-activity structure analysis from laps (standard library only).

Session aggregates can only *guess* tempo vs interval (via HR spread). Per-lap data
lets us read the workout the way a coach does — the lap structure is calibration-free:

  interval     — ≥3 similar fast laps with slow/rest laps interleaved (repeats)
  tempo        — one sustained fast block, no rest laps between
  progression  — laps get monotonically faster
  steady       — uniform effort (easy/long/recovery decided by the calibrated classifier)

It also reports pacing quality (negative split, fade, consistency) and detects auto-lap
recordings (all laps ≈1 km/mile) where rep detection is unreliable. Source-agnostic:
feed it normalized laps from a `.fit` file or the Strava detail endpoint (see adapters).
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional


def _fp(sec: Optional[float]) -> Optional[str]:
    if not sec:
        return None
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _norm(laps: List[dict]) -> List[dict]:
    """Keep laps with a usable distance + pace (pace_sec, or derived from duration/distance)."""
    out = []
    for lp in laps:
        km = lp.get("distance_km")
        dur = lp.get("duration_s")
        pace = lp.get("pace_sec")
        if pace is None and km and dur:
            pace = dur / km
        if km and pace and km > 0.05:
            out.append({"km": km, "pace": pace, "dur": dur,
                        "avg_hr": lp.get("avg_hr"), "max_hr": lp.get("max_hr")})
    return out


def _is_progression(paces: List[float]) -> bool:
    """Mostly-monotonic speed-up across the run (each lap ≤ a touch slower than the last)."""
    if len(paces) < 4:
        return False
    drops = sum(1 for a, b in zip(paces, paces[1:]) if b <= a + 3)  # faster or ~equal
    return drops >= len(paces) - 1 - 1 and paces[-1] < paces[0] - 15  # net faster, near-monotonic


def _rep_summary(work: List[dict]) -> str:
    km = statistics.mean([w["km"] for w in work])
    pace = statistics.mean([w["pace"] for w in work])
    hrs = [w["avg_hr"] for w in work if w.get("avg_hr")]
    hr = f", avg HR {round(statistics.mean(hrs))}" if hrs else ""
    dist = f"{round(km, 2):g} km" if abs(km - round(km)) > 0.05 else f"{int(round(km))} km"
    return f"{len(work)} × {dist} @ {_fp(pace)}/km{hr}"


def analyze_laps(laps: List[dict], distance_km: Optional[float] = None,
                 long_km: float = 19.0) -> Dict:
    """Analyze one activity's lap structure. Returns structure, reps, pacing, and a
    high-confidence OMPB `type` (None when the call should defer to the calibrated
    classifier — i.e. a steady run whose easy/tempo/recovery split needs the runner's bands)."""
    L = _norm(laps)
    n = len(L)
    total_km = distance_km or sum(x["km"] for x in L)
    base = {"laps": n, "reps": [], "rep_summary": None, "splits": None, "notes": []}

    if n < 3:
        return {**base, "structure": "unknown", "confidence": "low",
                "type": "long" if total_km >= long_km else None}

    paces = [x["pace"] for x in L]
    dists = [x["km"] for x in L]
    fast, slow = min(paces), max(paces)
    spread = slow - fast  # sec/km variation within the activity

    # Auto-lap (every ~1 km/mile) vs manual workout laps (varied distances incl. short rests).
    dmean = statistics.mean(dists)
    dcv = statistics.pstdev(dists) / dmean if dmean else 0
    auto_lap = dcv < 0.15 and 0.85 <= dmean <= 1.75

    # Pacing quality (any lap mode): split + consistency.
    half = n // 2
    first_half = statistics.mean(paces[:half])
    second_half = statistics.mean(paces[half:])
    pace_mean = statistics.mean(paces)
    splits = {
        "negative_split": second_half < first_half - 3,
        "fade_pct": round((second_half - first_half) / first_half * 100, 1),
        "consistency_cv": round(statistics.pstdev(paces) / pace_mean if pace_mean else 0, 3),
    }
    base["splits"] = splits

    SIG = 30  # sec/km — an intentional intensity swing (work vs rest)
    progression = _is_progression(paces)
    has_hr = any(x.get("avg_hr") for x in L)

    def _result(structure, typ, conf, notes, reps=None, rep_summary=None):
        return {**base, "structure": structure, "type": typ, "confidence": conf,
                "reps": reps or [], "rep_summary": rep_summary, "notes": notes}

    # The engine asserts a TYPE only for what the laps make UNAMBIGUOUS — interval (repeated
    # work with rests, confirmed by HR) and long (by distance). Pace varies on any run
    # (terrain, fatigue), so "this block is faster" alone is NOT tempo; the easy/tempo/recovery
    # call needs the runner's calibrated HR bands → type=None defers it to the classifier.
    if spread >= SIG:
        thresh = fast + spread * 0.45
        flags = [p <= thresh for p in paces]            # True = work lap (faster)
        work = [L[i] for i, f in enumerate(flags) if f]
        rest = [L[i] for i, f in enumerate(flags) if not f]
        work_idx = [i for i, f in enumerate(flags) if f]
        interleaved = any(not flags[i] for i in range(work_idx[0] + 1, work_idx[-1])) if len(work_idx) >= 2 else False
        work_pace_cv = (statistics.pstdev([w["pace"] for w in work]) / statistics.mean([w["pace"] for w in work])
                        if len(work) >= 2 else 0)
        # Intensity evidence: work laps at clearly higher HR than rest (≥12 bpm). Without HR,
        # require MANUAL laps (varied distances) — auto-lap pace wobble on an easy run is not work.
        wh = [w["avg_hr"] for w in work if w.get("avg_hr")]
        rh = [r["avg_hr"] for r in rest if r.get("avg_hr")]
        intense = (statistics.mean(wh) - statistics.mean(rh) >= 12) if (wh and rh) else (not has_hr and not auto_lap)
        # Real intervals have rest laps interleaved, so work is a *fraction* of laps; if
        # nearly every lap is "fast" it's a continuous run (esp. auto-lap), not repeats.
        reps_ok = (len(work) >= 3 and interleaved and work_pace_cv < 0.08
                   and len(work) <= 0.65 * n)

        if reps_ok and intense:
            durs = [L[i]["dur"] for i in range(work_idx[0], work_idx[-1] + 1)
                    if not flags[i] and L[i].get("dur")]
            notes = [_rep_summary(work)]
            if durs:
                notes.append(f"~{int(statistics.mean(durs))}s recovery between reps")
            if auto_lap:
                notes.append("auto-lap recording — rep count approximate")
            return _result("interval", "interval", "medium" if auto_lap else "high", notes,
                           reps=[{"km": round(w["km"], 2), "pace": _fp(w["pace"]), "avg_hr": w.get("avg_hr")} for w in work],
                           rep_summary=_rep_summary(work))

        if intense and not interleaved:
            # one sustained harder block — describe it; the easy/tempo call is the classifier's
            return _result("tempo", "long" if total_km >= long_km else None, "medium",
                           [f"sustained ~{_fp(statistics.mean([w['pace'] for w in work]))}/km block — "
                            "intensity from the calibrated classifier"])
        if progression and intense:
            return _result("progression", "long" if total_km >= long_km else None, "medium",
                           ["paces step down through the run — progression effort"])
        # variation without intensity evidence → just terrain/fatigue on a steady run; fall through.

    if progression:
        return _result("progression", "long" if total_km >= long_km else None, "low",
                       ["paces drift faster through the run"])
    return _result("steady", "long" if total_km >= long_km else None, "medium",
                   ["uniform-effort run — easy/tempo/recovery from the calibrated classifier"])
