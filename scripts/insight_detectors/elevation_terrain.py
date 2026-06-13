"""Elevation / terrain insight detectors.

Focus: vertical gain and hilly running — weekly cumulative ascent peaks, climbing-pace
improvement, flat-vs-hill pace gap shrinking, vert/km trend, single biggest climb, and a
volume-of-vertical adaptation angle distinct from core ``hill_adaptation`` (which compares a
single hilly run's pace to the flat average). All detectors follow the ``_util`` contract:
``def detector(runs, ctx) -> list[card]``, never raise, return [] unless a meaningful threshold
is cleared. Distance/pace/ascent/duration coverage is ~99%, so these lean on those fields.
"""
from __future__ import annotations

import datetime as _dt
from typing import List

from insight_detectors._util import card, fmt_pace, window, mean, median


def _vert_per_km(r: dict):
    """Ascent meters per km for a run, or None if not computable."""
    if r.get("ascent") is None or not r.get("dist") or r["dist"] <= 0:
        return None
    return r["ascent"] / r["dist"]


def weekly_ascent_peak(runs: List[dict], ctx: dict) -> List[dict]:
    """Most cumulative climbing packed into one ISO week, recently — a new vertical high."""
    today = ctx["today"]
    usable = [r for r in runs if r.get("ascent") is not None and r["ascent"] > 0]
    if len(usable) < 8:
        return []
    week_sum: dict = {}
    for r in usable:
        wk = r["date"].isocalendar()[:2]
        week_sum[wk] = week_sum.get(wk, 0.0) + r["ascent"]
    recent_wk = window(usable, today, -1, 14)
    if not recent_wk:
        return []
    recent_weeks = {r["date"].isocalendar()[:2] for r in recent_wk}
    recent_best_wk = max(recent_weeks, key=lambda w: week_sum.get(w, 0.0))
    recent_best = week_sum.get(recent_best_wk, 0.0)
    prior = {w: v for w, v in week_sum.items() if w not in recent_weeks}
    if len(prior) < 3 or recent_best < 200:
        return []
    prior_best = max(prior.values())
    if recent_best <= prior_best * 1.1:
        return []
    return [card(
        "weekly_ascent_peak", "pr", "🏔️",
        f"한 주 누적 상승 {int(round(recent_best))}m",
        (f"한 주 동안 누적 {int(round(recent_best))}m를 올랐어요. 기존 최다 한 주({int(round(prior_best))}m)를 "
         f"넘어선 역대 최대 등반량 — 다리 근지구력에 그만큼 큰 자극이 들어간 한 주예요."),
        {"week_ascent_m": int(round(recent_best)), "prev_best_m": int(round(prior_best)),
         "n_weeks_prior": len(prior)},
        min(1.0, 0.5 + (recent_best - prior_best) / 1200),
        (f"한 주 누적 상승 {int(round(recent_best))}m로 기존 최다 {int(round(prior_best))}m 경신. "
         f"등반 부하 의미와 회복·다음 주 운영 코칭."))]


def climbing_pace_improvement(runs: List[dict], ctx: dict) -> List[dict]:
    """On comparably hilly runs (vert/km >= 10), is climbing pace getting faster? Recent ~6 weeks
    vs 7–20 weeks ago, matched on terrain so the comparison is fair."""
    today = ctx["today"]
    hilly = [r for r in runs
             if _vert_per_km(r) is not None and _vert_per_km(r) >= 10 and r.get("pace_s")]
    if len(hilly) < 6:
        return []
    recent = window(hilly, today, -1, 42)
    base = window(hilly, today, 49, 140)
    if len(recent) < 3 or len(base) < 3:
        return []
    rp = mean(r["pace_s"] for r in recent)
    bp = mean(r["pace_s"] for r in base)
    rv = mean(_vert_per_km(r) for r in recent)
    bv = mean(_vert_per_km(r) for r in base)
    if rp is None or bp is None or rv is None or bv is None:
        return []
    # Terrain must be comparable (within 4 m/km) so we are not just comparing flatter routes.
    if abs(rv - bv) > 4:
        return []
    delta = bp - rp
    if delta < 10:
        return []
    return [card(
        "climbing_pace_improvement", "improvement", "📈",
        f"오르막 페이스 {int(round(delta))}초 빨라졌어요",
        (f"비슷한 경사(약 {int(round(rv))}m/km) 언덕 코스에서 최근 6주 평균이 {fmt_pace(rp)}/km예요. "
         f"두세 달 전 같은 경사대에선 {fmt_pace(bp)}/km였으니 {int(round(delta))}초/km 빨라진 셈 — "
         f"오르막을 미는 힘이 확실히 늘었어요."),
        {"recent_pace": fmt_pace(rp), "base_pace": fmt_pace(bp), "delta_s": int(round(delta)),
         "recent_vpk": int(round(rv)), "base_vpk": int(round(bv)),
         "n_recent": len(recent), "n_base": len(base)},
        min(1.0, 0.5 + delta / 70),
        (f"비슷한 경사({int(round(rv))}m/km) 언덕에서 오르막 페이스 {fmt_pace(bp)}→{fmt_pace(rp)}/km "
         f"({int(round(delta))}초/km 개선). 언덕 추진력 향상 의미·다음 자극 코칭."))]


def flat_hill_gap_narrowing(runs: List[dict], ctx: dict) -> List[dict]:
    """Is the pace penalty for hills shrinking? Compare (hill pace - flat pace) gap recently vs
    earlier. A smaller gap means hills slow you down less than they used to."""
    today = ctx["today"]

    def gap(lo, hi):
        seg = window(runs, today, lo, hi)
        flat = [r["pace_s"] for r in seg
                if _vert_per_km(r) is not None and _vert_per_km(r) < 5 and r.get("pace_s")]
        hill = [r["pace_s"] for r in seg
                if _vert_per_km(r) is not None and _vert_per_km(r) >= 12 and r.get("pace_s")]
        if len(flat) < 2 or len(hill) < 2:
            return None
        return median(hill) - median(flat), median(flat), median(hill)

    recent = gap(-1, 49)
    base = gap(49, 160)
    if recent is None or base is None:
        return []
    recent_gap, rflat, rhill = recent
    base_gap, _bflat, _bhill = base
    if base_gap <= 0:
        return []
    shrink = base_gap - recent_gap
    if shrink < 12 or recent_gap < 0:
        return []
    return [card(
        "flat_hill_gap_narrowing", "adaptation", "⛰️",
        f"언덕 페널티 {int(round(shrink))}초 줄었어요",
        (f"예전엔 언덕 코스가 평지보다 {int(round(base_gap))}초/km 느렸는데, 최근엔 그 차이가 "
         f"{int(round(recent_gap))}초/km로 좁혀졌어요. 같은 오르막도 예전만큼 발목을 잡지 않는다는 신호예요."),
        {"recent_gap_s": int(round(recent_gap)), "base_gap_s": int(round(base_gap)),
         "shrink_s": int(round(shrink)), "recent_flat_pace": fmt_pace(rflat),
         "recent_hill_pace": fmt_pace(rhill)},
        min(1.0, 0.5 + shrink / 60),
        (f"언덕-평지 페이스 격차 {int(round(base_gap))}→{int(round(recent_gap))}초/km로 축소"
         f"({int(round(shrink))}초 개선). 언덕 적응이 페이스 안정으로 이어진 점 코칭."))]


def vert_per_km_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Are you seeking out more vertical lately? Average vert/km across all runs rising over months
    — a training-choice signal, not just one big climb."""
    today = ctx["today"]
    vpk = [(r, _vert_per_km(r)) for r in runs]
    vpk = [(r, v) for r, v in vpk if v is not None]
    if len(vpk) < 10:
        return []
    recent = [v for r, v in vpk if (today - r["date"]).days <= 42]
    base = [v for r, v in vpk if 49 < (today - r["date"]).days <= 140]
    if len(recent) < 4 or len(base) < 4:
        return []
    rm = mean(recent)
    bm = mean(base)
    if rm is None or bm is None or bm <= 0:
        return []
    delta = rm - bm
    # Require a clear absolute jump and at least ~40% more vertical density.
    if delta < 4 or rm < bm * 1.4:
        return []
    pct = int(round((rm / bm - 1) * 100))
    return [card(
        "vert_per_km_trend", "improvement", "📐",
        f"km당 상승 +{int(round(delta))}m (+{pct}%)",
        (f"최근 6주 러닝은 1km당 평균 {int(round(rm))}m를 올라요. 두세 달 전({int(round(bm))}m/km)보다 "
         f"{pct}% 더 가팔라진 코스 — 의식적으로 언덕을 더 찾고 있다는 뜻이고, 다리엔 좋은 누적 자극이에요."),
        {"recent_vpk": int(round(rm)), "base_vpk": int(round(bm)),
         "delta_vpk": int(round(delta)), "pct": pct, "n_recent": len(recent), "n_base": len(base)},
        min(0.85, 0.4 + delta / 30),
        (f"평균 등반 밀도 {int(round(bm))}→{int(round(rm))}m/km(+{pct}%) 상승. "
         f"언덕 훈련 비중 증가의 의미와 평지 스피드와의 균형 코칭."))]


def single_biggest_climb(runs: List[dict], ctx: dict) -> List[dict]:
    """A single run with the most cumulative ascent ever, set recently — a standout effort."""
    today = ctx["today"]
    usable = [r for r in runs if r.get("ascent") is not None and r["ascent"] > 0 and r.get("dist")]
    if len(usable) < 8:
        return []
    recent = window(usable, today, -1, 21)
    prior = [r for r in usable if (today - r["date"]).days > 21]
    if not recent or len(prior) < 6:
        return []
    rbig = max(recent, key=lambda r: r["ascent"])
    pbig = max((r["ascent"] for r in prior), default=0.0)
    if pbig <= 0 or rbig["ascent"] <= pbig or rbig["ascent"] < 250:
        return []
    vpk = _vert_per_km(rbig)
    return [card(
        "single_biggest_climb", "pr", "🧗",
        f"단일 최대 등반 {int(round(rbig['ascent']))}m",
        (f"{rbig['dist']:.1f}km를 달리며 누적 {int(round(rbig['ascent']))}m를 올랐어요. 한 번의 러닝으로는 "
         f"역대 가장 많이 오른 기록(기존 {int(round(pbig))}m)이에요 — 등반 지구력의 새 영역을 밟았어요."),
        {"ascent_m": int(round(rbig["ascent"])), "prev_best_m": int(round(pbig)),
         "distance_km": round(rbig["dist"], 1), "vert_per_km": round(vpk, 1) if vpk else None,
         "date": rbig["date"].isoformat()},
        min(1.0, 0.5 + (rbig["ascent"] - pbig) / 800),
        (f"단일 러닝 최대 등반 {int(round(rbig['ascent']))}m({rbig['dist']:.1f}km) 경신, 기존 {int(round(pbig))}m. "
         f"등반 지구력 의미와 회복·근육통 관리 코칭."))]


def hill_volume_adaptation(runs: List[dict], ctx: dict) -> List[dict]:
    """Volume-of-vertical adaptation (distinct from core hill_adaptation's single-run pace test):
    over the last 6 weeks you are absorbing a large total climb load across many runs without it
    blunting your easy pace — your legs handle sustained vertical now."""
    today = ctx["today"]
    last6 = window(runs, today, -1, 42)
    hilly = [r for r in last6
             if r.get("ascent") is not None and r["ascent"] > 0 and r.get("dist")]
    if len(hilly) < 4:
        return []
    total_ascent = sum(r["ascent"] for r in hilly)
    n_hill_sessions = sum(1 for r in hilly if (_vert_per_km(r) or 0) >= 10)
    if total_ascent < 1000 or n_hill_sessions < 3:
        return []
    # Easy/recovery pace should be holding (not degraded) despite the climbing load:
    easy_recent = [r["pace_s"] for r in last6
                   if r["type"] in ("easy", "recovery") and r.get("pace_s")
                   and (_vert_per_km(r) or 0) < 8]
    easy_base = [r["pace_s"] for r in window(runs, today, 49, 140)
                 if r["type"] in ("easy", "recovery") and r.get("pace_s")
                 and (_vert_per_km(r) or 0) < 8]
    if len(easy_recent) < 3 or len(easy_base) < 3:
        return []
    re_pace = median(easy_recent)
    be_pace = median(easy_base)
    if re_pace is None or be_pace is None:
        return []
    # Adaptation: heavy climbing volume AND flat-easy pace not slower (allow tiny drift +3s).
    if re_pace - be_pace > 3:
        return []
    return [card(
        "hill_volume_adaptation", "adaptation", "🏞️",
        f"6주간 누적 {int(round(total_ascent))}m, 평지 페이스 유지",
        (f"최근 6주 동안 언덕 세션 {n_hill_sessions}회로 누적 {int(round(total_ascent))}m를 올랐는데도 "
         f"평지 이지런이 {fmt_pace(re_pace)}/km로 그대로예요. 큰 등반 부하를 소화하면서도 기본 페이스가 "
         f"흔들리지 않는 건 다리가 언덕 볼륨에 적응했다는 뜻이에요."),
        {"total_ascent_m": int(round(total_ascent)), "hill_sessions": n_hill_sessions,
         "recent_easy_pace": fmt_pace(re_pace), "base_easy_pace": fmt_pace(be_pace)},
        min(0.85, 0.45 + total_ascent / 6000),
        (f"6주 누적 등반 {int(round(total_ascent))}m({n_hill_sessions}회 언덕 세션) 소화하며 평지 이지런 "
         f"{fmt_pace(be_pace)}→{fmt_pace(re_pace)}/km 유지. 등반 볼륨 적응 의미·다음 빌드업 코칭."))]


def downhill_volume_note(runs: List[dict], ctx: dict) -> List[dict]:
    """A recent long, hilly run with notable descent load — surfaced as a quad/eccentric-load
    awareness card (descent ≈ ascent on out-and-back/loop courses; flag big-ascent long runs)."""
    today = ctx["today"]
    recent = window(runs, today, -1, 10)
    cand = [r for r in recent
            if r.get("ascent") is not None and r.get("dist") and r["dist"] >= 12
            and (_vert_per_km(r) or 0) >= 10]
    if not cand:
        return []
    r = max(cand, key=lambda x: x["ascent"])
    # Only worth flagging when the climb (and thus likely the descent) is substantial.
    if r["ascent"] < 300:
        return []
    vpk = _vert_per_km(r)
    return [card(
        "downhill_volume_note", "warning", "🦵",
        f"롱런 {r['dist']:.1f}km · 상승 {int(round(r['ascent']))}m",
        (f"{r['dist']:.1f}km에 누적 상승 {int(round(r['ascent']))}m({int(round(vpk))}m/km) 코스를 달렸어요. "
         f"오른 만큼 내려왔다는 뜻이라 허벅지 앞쪽(대퇴사두) 이심성 부하가 큽니다. 다음 1~2일은 가볍게, "
         f"계단 내려갈 때 통증이 오면 회복을 우선하세요."),
        {"distance_km": round(r["dist"], 1), "ascent_m": int(round(r["ascent"])),
         "vert_per_km": round(vpk, 1) if vpk else None, "date": r["date"].isoformat()},
        min(0.7, 0.35 + r["ascent"] / 2000),
        (f"롱런 {r['dist']:.1f}km/상승 {int(round(r['ascent']))}m로 내리막 이심성 부하 큼. "
         f"대퇴사두 회복·근육통(DOMS) 관리와 다음 며칠 운영 코칭."))]


DETECTORS = [
    weekly_ascent_peak,
    climbing_pace_improvement,
    flat_hill_gap_narrowing,
    vert_per_km_trend,
    single_biggest_climb,
    hill_volume_adaptation,
    downhill_volume_note,
]
