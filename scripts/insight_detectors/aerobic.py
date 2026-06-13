"""Aerobic / heart-rate efficiency insight detectors.

Deep-dive on aerobic engine + HR efficiency: same-pace HR drop, efficiency-coefficient
(pace_s/hr) trend, rising easy-pace ceiling, long-run decoupling (HR drift across lap_series),
Z2 time-share trend, easy-HR variability stabilizing, etc.

These complement core.aerobic_efficiency (do NOT duplicate it). HR/cadence exist on only ~40%
of runs, so HR-based detectors guard on sample size and return [] when data is thin.
All detectors are defensive (never raise) and follow the _util contract.
"""
from __future__ import annotations

import statistics as _st
from typing import List

from insight_detectors._util import card, fmt_pace, window, mean, has

EASY_TYPES = ("easy", "recovery", "long")


def _f(v):
    """Coerce to float or return None."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def same_pace_hr_drop(runs: List[dict], ctx: dict) -> List[dict]:
    """At the SAME easy pace band, is heart rate dropping? Mirror image of core's
    same-HR-faster signal: hold pace constant, watch HR fall. Matches easy/recovery/long
    runs within a +-10 s/km band around the median easy pace; recent ~5wk vs 8-20wk ago."""
    try:
        today = ctx["today"]
        easy = [r for r in runs if r.get("type") in EASY_TYPES and has(r, "hr", "pace_s")]
        if len(easy) < 8:
            return []
        paces = sorted(r["pace_s"] for r in easy)
        med = paces[len(paces) // 2]
        band = [r for r in easy if abs(r["pace_s"] - med) <= 10]
        recent, base = window(band, today, 0, 35), window(band, today, 56, 140)
        if len(recent) < 3 or len(base) < 3:
            return []
        rp, rh = mean(r["pace_s"] for r in recent), mean(r["hr"] for r in recent)
        bp, bh = mean(r["pace_s"] for r in base), mean(r["hr"] for r in base)
        if None in (rp, rh, bp, bh):
            return []
        drop = bh - rh
        # pace must be held roughly constant, HR must fall meaningfully
        if drop < 4 or abs(rp - bp) > 8:
            return []
        return [card(
            "same_pace_hr_drop", "improvement", "💗",
            f"같은 페이스, 심박 {int(round(drop))}bpm 낮아졌어요",
            (f"최근 한 달 이지런이 {fmt_pace(rp)}/km에 평균 {round(rh)}bpm이에요. 두세 달 전 거의 같은 "
             f"페이스({fmt_pace(bp)}/km)엔 {round(bh)}bpm이었으니 같은 속도를 {int(round(drop))}bpm 더 "
             f"편하게 달린다는 뜻 — 심장이 한 박동에 더 많은 일을 하고 있어요."),
            {"pace": fmt_pace(rp), "recent_hr": round(rh), "base_hr": round(bh),
             "drop_bpm": int(round(drop)), "n_recent": len(recent), "n_base": len(base)},
            min(1.0, 0.5 + drop / 20),
            (f"같은 이지 페이스({fmt_pace(rp)}/km)에서 평균 심박이 {round(bh)}→{round(rh)}bpm로 "
             f"{int(round(drop))}bpm 내려감. 유산소 기반이 두꺼워졌다는 신호 — 의미와 다음 단계 코칭."))]
    except Exception:
        return []


def efficiency_coeff_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Efficiency coefficient = pace_s / hr (seconds per km per heartbeat). Lower is better:
    fewer beats to cover the same ground. Tracks the easy-run coefficient recent vs base."""
    try:
        today = ctx["today"]
        easy = [r for r in runs if r.get("type") in EASY_TYPES and has(r, "hr", "pace_s") and r["hr"] > 0]
        recent = [r["pace_s"] / r["hr"] for r in easy if (today - r["date"]).days <= 35]
        base = [r["pace_s"] / r["hr"] for r in easy if 56 < (today - r["date"]).days <= 140]
        if len(recent) < 4 or len(base) < 4:
            return []
        rc, bc = mean(recent), mean(base)
        if None in (rc, bc) or bc <= 0:
            return []
        improve = (bc - rc) / bc * 100.0  # percent reduction in s/km per beat
        if improve < 2.5:
            return []
        return [card(
            "efficiency_coeff_trend", "improvement", "📊",
            f"심박당 효율 {improve:.0f}% 좋아졌어요",
            (f"1박동으로 나아가는 거리를 보는 효율계수(페이스÷심박)가 두세 달 전보다 {improve:.0f}% "
             f"좋아졌어요. 같은 심박으로 더 멀리, 더 빠르게 — 천천히 쌓은 유산소 훈련이 숫자로 드러나는 부분이에요."),
            {"recent_coeff": round(rc, 3), "base_coeff": round(bc, 3),
             "improve_pct": round(improve, 1), "n_recent": len(recent), "n_base": len(base)},
            min(0.9, 0.4 + improve / 25),
            (f"이지런 효율계수(pace_s/hr) {round(bc, 3)}→{round(rc, 3)}, {improve:.0f}% 개선. "
             f"심박 효율 향상의 의미·유지법 코칭."))]
    except Exception:
        return []


def easy_pace_ceiling_rise(runs: List[dict], ctx: dict) -> List[dict]:
    """The easy-pace ceiling: fastest pace still run at a genuinely easy effort (low HR band).
    If the runner can now hold a faster pace while staying easy, the aerobic ceiling rose."""
    try:
        today = ctx["today"]
        pool = [r for r in runs if r.get("type") in ("easy", "recovery") and has(r, "hr", "pace_s")]
        if len(pool) < 8:
            return []
        hrs = sorted(r["hr"] for r in pool)
        med_hr = hrs[len(hrs) // 2]
        # genuinely easy = at or below the median easy HR
        easy_band = [r for r in pool if r["hr"] <= med_hr + 3]
        recent = [r for r in easy_band if (today - r["date"]).days <= 35]
        base = [r for r in easy_band if 56 < (today - r["date"]).days <= 140]
        if len(recent) < 3 or len(base) < 3:
            return []
        # ceiling = fastest (min pace_s) easy run in each window
        rceil = min(r["pace_s"] for r in recent)
        bceil = min(r["pace_s"] for r in base)
        gain = bceil - rceil
        if gain < 10:
            return []
        return [card(
            "easy_pace_ceiling_rise", "improvement", "🚀",
            f"편한 호흡 한계 페이스 {int(round(gain))}초 빨라졌어요",
            (f"심박을 낮게(이지 영역) 유지하면서 낼 수 있는 가장 빠른 페이스가 {fmt_pace(bceil)}/km에서 "
             f"{fmt_pace(rceil)}/km로 올라갔어요. 숨이 차지 않는 구간 자체가 빨라진 것 — 레이스에서 "
             f"여유 구간이 넓어진다는 뜻이에요."),
            {"recent_ceiling": fmt_pace(rceil), "base_ceiling": fmt_pace(bceil),
             "gain_s": int(round(gain)), "hr_cap": round(med_hr + 3),
             "n_recent": len(recent), "n_base": len(base)},
            min(0.9, 0.42 + gain / 70),
            (f"이지 심박 한계 페이스 {fmt_pace(bceil)}→{fmt_pace(rceil)}/km, {int(round(gain))}초 향상. "
             f"유산소 천장 상승의 레이스 활용법 코칭."))]
    except Exception:
        return []


def long_run_decoupling(runs: List[dict], ctx: dict) -> List[dict]:
    """Long-run cardiac decoupling from deep lap_series: HR drift between first and second half
    at a steady pace. Low drift (<5%) = strong durability; observed on a single recent long run."""
    try:
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        today = ctx["today"]
        by_id = {r.get("source_id"): r for r in runs}
        best = None  # (drift_pct, run, laps)
        for sid, an in deep.items():
            if not isinstance(an, dict):
                continue
            run = by_id.get(sid)
            if run is None or run.get("type") != "long":
                continue
            if (today - run["date"]).days > 45:
                continue
            laps = an.get("lap_series")
            if not isinstance(laps, list) or len(laps) < 4:
                continue
            hr_laps = [_f(l.get("avg_hr")) for l in laps if isinstance(l, dict)]
            hr_laps = [h for h in hr_laps if h and h > 0]
            if len(hr_laps) < 4:
                continue
            half = len(hr_laps) // 2
            first = mean(hr_laps[:half])
            second = mean(hr_laps[half:])
            if not first or first <= 0 or not second:
                continue
            drift = (second - first) / first * 100.0
            if best is None or drift < best[0]:
                best = (drift, run, laps)
        if best is None:
            return []
        drift, run, laps = best
        # only a low/controlled drift is praiseworthy durability
        if drift > 5.0:
            return []
        dist = run.get("dist")
        dtxt = f"{dist:.1f}km " if dist else ""
        return [card(
            "long_run_decoupling", "adaptation", "🫀",
            f"롱런 후반 심박 드리프트 {drift:.1f}%",
            (f"최근 {dtxt}롱런에서 후반 평균 심박이 전반 대비 {drift:.1f}%밖에 오르지 않았어요. "
             f"보통 길어질수록 같은 페이스에 심박이 슬금슬금 오르는데(디커플링), 이게 5% 아래면 "
             f"지구력 기반이 단단하다는 강한 증거예요."),
            {"drift_pct": round(drift, 1), "distance_km": round(dist, 1) if dist else None,
             "n_laps": len(laps), "date": run["date"].isoformat()},
            min(0.85, 0.5 + (5.0 - drift) / 12),
            (f"롱런 전·후반 심박 드리프트 {drift:.1f}%(5% 미만=우수). "
             f"카디악 디커플링이 낮다는 것의 의미와 페이스 운영 코칭."))]
    except Exception:
        return []


def long_run_decoupling_warn(runs: List[dict], ctx: dict) -> List[dict]:
    """Flip side: a recent long run with high HR drift (>=10%) at steady pace signals the
    aerobic ceiling or fueling/hydration limited durability — a coachable target."""
    try:
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        today = ctx["today"]
        by_id = {r.get("source_id"): r for r in runs}
        worst = None
        for sid, an in deep.items():
            if not isinstance(an, dict):
                continue
            run = by_id.get(sid)
            if run is None or run.get("type") != "long":
                continue
            if (today - run["date"]).days > 45:
                continue
            laps = an.get("lap_series")
            if not isinstance(laps, list) or len(laps) < 4:
                continue
            hr_laps = [_f(l.get("avg_hr")) for l in laps if isinstance(l, dict)]
            hr_laps = [h for h in hr_laps if h and h > 0]
            if len(hr_laps) < 4:
                continue
            half = len(hr_laps) // 2
            first = mean(hr_laps[:half])
            second = mean(hr_laps[half:])
            if not first or first <= 0 or not second:
                continue
            drift = (second - first) / first * 100.0
            if worst is None or drift > worst[0]:
                worst = (drift, run, laps)
        if worst is None:
            return []
        drift, run, laps = worst
        if drift < 10.0:
            return []
        dist = run.get("dist")
        dtxt = f"{dist:.1f}km " if dist else ""
        return [card(
            "long_run_decoupling_warn", "warning", "📉",
            f"롱런 후반 심박 +{drift:.0f}% 상승",
            (f"최근 {dtxt}롱런에서 후반 심박이 전반보다 {drift:.0f}% 올랐어요. 페이스가 비슷한데 심박만 "
             f"오른다면 아직 그 거리의 유산소 여유가 빠듯하거나 수분·연료가 부족했다는 신호 — 다음엔 "
             f"전반을 조금 더 보수적으로 가져가 보세요."),
            {"drift_pct": round(drift, 1), "distance_km": round(dist, 1) if dist else None,
             "n_laps": len(laps), "date": run["date"].isoformat()},
            min(0.8, 0.4 + (drift - 10.0) / 25),
            (f"롱런 전·후반 심박 드리프트 {drift:.0f}%(10% 이상). 페이싱·연료·유산소 여유 관점 코칭."))]
    except Exception:
        return []


def z2_share_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Zone-2 time share trend from deep time_in_zone_pct. More easy aerobic volume (Z1+Z2)
    relative to a wider history is the classic base-building pattern. Uses deep recent runs."""
    try:
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        today = ctx["today"]
        by_id = {r.get("source_id"): r for r in runs}
        shares = []  # (days_ago, z1z2_pct)
        for sid, an in deep.items():
            if not isinstance(an, dict):
                continue
            run = by_id.get(sid)
            if run is None:
                continue
            tz = an.get("time_in_zone_pct")
            if not isinstance(tz, dict):
                continue
            z1 = _f(tz.get("Z1")) or 0.0
            z2 = _f(tz.get("Z2")) or 0.0
            total = sum((_f(tz.get(f"Z{i}")) or 0.0) for i in range(1, 6))
            if total <= 0:
                continue
            # normalize in case values are fractions vs percents
            share = (z1 + z2) / total * 100.0
            shares.append((run, share))
        if len(shares) < 3:
            return []
        avg_share = mean(s for _, s in shares)
        if avg_share is None or avg_share < 65:
            return []
        # representative run = highest easy share among recent deep runs
        rep_run, rep_share = max(shares, key=lambda x: x[1])
        return [card(
            "z2_share_trend", "consistency", "🟢",
            f"최근 러닝 {int(round(avg_share))}%가 Z1-Z2 유산소 구간",
            (f"최근 분석된 러닝들의 평균 {int(round(avg_share))}%를 낮은 심박(Z1-Z2)에서 보냈어요. "
             f"느린 거리가 유산소 모세혈관과 미토콘드리아를 키우는 핵심 — 80/20 원칙에 잘 맞는 비율이에요."),
            {"avg_z1z2_pct": int(round(avg_share)), "best_share_pct": int(round(rep_share)),
             "n_runs": len(shares)},
            min(0.75, 0.35 + (avg_share - 65) / 80),
            (f"최근 deep 러닝 평균 Z1-Z2 비중 {int(round(avg_share))}%. "
             f"저강도 유산소 볼륨의 가치와 80/20 분배 코칭."))]
    except Exception:
        return []


def easy_hr_stabilizing(runs: List[dict], ctx: dict) -> List[dict]:
    """Easy-run HR variability shrinking: a tighter spread of easy HR (lower stdev) recent vs
    base means more repeatable pacing/effort control — a subtle aerobic-control signal."""
    try:
        today = ctx["today"]
        easy = [r for r in runs if r.get("type") in EASY_TYPES and has(r, "hr")]
        recent = [r["hr"] for r in easy if (today - r["date"]).days <= 42]
        base = [r["hr"] for r in easy if 56 < (today - r["date"]).days <= 140]
        if len(recent) < 5 or len(base) < 5:
            return []
        rsd = _st.pstdev(recent)
        bsd = _st.pstdev(base)
        if bsd <= 0:
            return []
        drop = bsd - rsd
        # require both a meaningful absolute and relative tightening
        if drop < 2 or drop / bsd < 0.2:
            return []
        return [card(
            "easy_hr_stabilizing", "consistency", "🎯",
            f"이지런 심박 편차 {bsd:.0f}→{rsd:.0f}bpm로 안정",
            (f"이지런 평균 심박의 들쭉날쭉함이 두세 달 전 ±{bsd:.0f}bpm에서 ±{rsd:.0f}bpm로 줄었어요. "
             f"매번 비슷한 강도로 달린다는 뜻 — 페이스·노력 조절이 몸에 배었고 회복도 일정해졌다는 신호예요."),
            {"recent_sd": round(rsd, 1), "base_sd": round(bsd, 1),
             "n_recent": len(recent), "n_base": len(base)},
            min(0.7, 0.32 + drop / 15),
            (f"이지런 심박 표준편차 {bsd:.0f}→{rsd:.0f}bpm로 축소. "
             f"강도 일관성·페이싱 제어가 좋아진 의미 코칭."))]
    except Exception:
        return []


def hr_reserve_pace_gain(runs: List[dict], ctx: dict) -> List[dict]:
    """Aerobic headroom: easy runs are settling into a lower fraction of max HR while pace holds
    or improves. Uses runs that carry both avg hr and max_hr; recent vs base %HRmax at easy."""
    try:
        today = ctx["today"]
        easy = [r for r in runs
                if r.get("type") in EASY_TYPES and has(r, "hr", "max_hr", "pace_s")
                and r["max_hr"] and r["max_hr"] > 0 and r["hr"] <= r["max_hr"]]
        if len(easy) < 8:
            return []

        def frac(r):
            return r["hr"] / r["max_hr"] * 100.0

        recent = [r for r in easy if (today - r["date"]).days <= 42]
        base = [r for r in easy if 56 < (today - r["date"]).days <= 140]
        if len(recent) < 3 or len(base) < 3:
            return []
        rf, bf = mean(frac(r) for r in recent), mean(frac(r) for r in base)
        rp, bp = mean(r["pace_s"] for r in recent), mean(r["pace_s"] for r in base)
        if None in (rf, bf, rp, bp):
            return []
        drop = bf - rf  # percentage-point drop in %HRmax
        # easy effort eased AND pace did not get slower
        if drop < 2.0 or rp > bp + 6:
            return []
        return [card(
            "hr_reserve_pace_gain", "adaptation", "🫁",
            f"이지런 최대심박 비율 {drop:.0f}%p 낮아졌어요",
            (f"이지런이 최대심박의 {bf:.0f}%에서 {rf:.0f}%로 내려왔어요(페이스는 {fmt_pace(bp)}→{fmt_pace(rp)}/km). "
             f"같은 거리를 더 낮은 강도로 소화한다는 뜻 — 힘든 훈련을 받아낼 유산소 여유가 늘었어요."),
            {"recent_pct_hrmax": round(rf), "base_pct_hrmax": round(bf),
             "drop_pp": round(drop, 1), "recent_pace": fmt_pace(rp), "base_pace": fmt_pace(bp),
             "n_recent": len(recent), "n_base": len(base)},
            min(0.8, 0.38 + drop / 12),
            (f"이지런 %HRmax {bf:.0f}→{rf:.0f}%(페이스 유지/개선). "
             f"유산소 여유 확대의 의미와 강훈련 배치 코칭."))]
    except Exception:
        return []


DETECTORS = [
    same_pace_hr_drop,
    efficiency_coeff_trend,
    easy_pace_ceiling_rise,
    long_run_decoupling,
    long_run_decoupling_warn,
    z2_share_trend,
    easy_hr_stabilizing,
    hr_reserve_pace_gain,
]
