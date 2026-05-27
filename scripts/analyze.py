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


def _smooth(xs: List[Optional[float]], w: int = 15) -> List[Optional[float]]:
    """Centered moving average (window w), skipping None — tames per-second GPS/HR noise."""
    n = len(xs)
    out: List[Optional[float]] = []
    for i in range(n):
        seg = [x for x in xs[max(0, i - w // 2):min(n, i + w // 2 + 1)] if x is not None]
        out.append(sum(seg) / len(seg) if seg else None)
    return out


def _zone_idx(hr: float, hrmax: float) -> int:
    """5-zone index by %HRmax: Z1<60 Z2 60–70 Z3 70–80 Z4 80–90 Z5 ≥90."""
    f = hr / hrmax
    for i, edge in enumerate((0.60, 0.70, 0.80, 0.90)):
        if f < edge:
            return i
    return 4


def analyze_streams(streams: dict, hrmax: Optional[float] = None) -> Dict:
    """Per-second stream metrics that laps can't give: aerobic decoupling (Pa:HR drift),
    time-in-HR-zone, and a stream-derived count of hard efforts (resolves auto-lap
    structure ambiguity). ``streams`` = parallel arrays {time, heartrate, velocity}.
    Returns only what the data supports (decoupling needs HR+velocity; zones/efforts need hrmax)."""
    hr = streams.get("heartrate") or []
    vel = streams.get("velocity") or []
    t = streams.get("time")
    n = min(len(hr), len(vel)) if (hr and vel) else 0
    out: Dict = {}
    if n < 60:
        return out

    moving = [i for i in range(n) if vel[i] and vel[i] > 0.5 and hr[i]]
    # Aerobic decoupling: efficiency = avg-speed / avg-HR per half; does it fade 1st→2nd? (>5% =
    # drift). Use ratio-of-means (stable vs per-sample noise), and only for a STEADY effort —
    # on intervals/stop-go runs the halves differ by structure, not drift, so it's not meaningful.
    if len(moving) >= 120:
        mvel = [vel[i] for i in moving]
        vcv = statistics.pstdev(mvel) / statistics.mean(mvel) if statistics.mean(mvel) else 1
        # Drop the first ~5 min (cold-start HR ramp inflates first-half efficiency).
        t0 = t[moving[0]] if (t and t[moving[0]] is not None) else None
        steady = [i for i in moving if t0 is not None and t[i] is not None and t[i] - t0 >= 300] or moving[len(moving) // 6:]
        dur = (t[steady[-1]] - t[steady[0]]) if (t and steady and t[steady[-1]] is not None) else len(steady)
        if vcv < 0.25 and len(steady) >= 120 and dur >= 900:  # steady, post-warmup, ≥15 min
            half = len(steady) // 2
            ef1 = statistics.mean(vel[i] for i in steady[:half]) / statistics.mean(hr[i] for i in steady[:half])
            ef2 = statistics.mean(vel[i] for i in steady[half:]) / statistics.mean(hr[i] for i in steady[half:])
            dec = round((ef1 - ef2) / ef1 * 100, 1) if ef1 else 0.0
            out["decoupling_pct"] = dec
            out["decoupling_note"] = ("high aerobic decoupling (>5%) — durability/fueling/heat limiter"
                                      if dec > 5 else "well-coupled — aerobically durable for this effort")

    if hrmax and hr:
        secs = [0.0] * 5
        for i in range(n):
            if not hr[i]:
                continue
            dt = (t[i] - t[i - 1]) if (t and i > 0 and t[i] and t[i - 1]) else 1
            dt = 1 if (dt <= 0 or dt > 30) else dt  # guard pauses/gaps
            secs[_zone_idx(hr[i], hrmax)] += dt
        total = sum(secs) or 1
        out["time_in_zone_s"] = {f"Z{i + 1}": int(secs[i]) for i in range(5)}
        out["time_in_zone_pct"] = {f"Z{i + 1}": round(secs[i] / total * 100) for i in range(5)}

        # Hard efforts: smoothed HR sustained in Z4+ (≥0.85·HRmax) for ≥45s. A continuous
        # tempo → 1 bout; N×reps → ~N bouts — corroborates/sharpens the lap structure.
        sm = _smooth([h if h else None for h in hr], 15)
        floor = 0.85 * hrmax
        bouts, run = 0, 0
        for i in range(n):
            hot = sm[i] is not None and sm[i] >= floor
            dt = (t[i] - t[i - 1]) if (t and i > 0 and t[i] and t[i - 1]) else 1
            dt = 1 if (dt <= 0 or dt > 30) else dt
            run = run + dt if hot else 0
            if hot and run - dt < 45 <= run:  # crossed the 45s sustain threshold → new bout
                bouts += 1
        out["hard_efforts"] = bouts
    return out


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
