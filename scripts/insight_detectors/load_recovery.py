"""Load & recovery insight detectors.

Focus: training-load distribution and recovery hygiene. These complement (never duplicate)
core ``load_spike`` (ACWR). Signals here are about *how* load is structured over time:
ramp rate, monotony, strain, rest gaps, hard:easy polarization, consecutive hard days,
recovery-run discipline, and deload detection. See ``_util`` for the detector/card contract.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from typing import List

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has

_HARD = ("tempo", "interval")
_EASY = ("easy", "recovery", "long")


def _daily_loads(runs: List[dict], today, days: int) -> List[float]:
    """Per-day total distance (km) over the trailing ``days`` window, oldest→newest."""
    buckets = {}
    for r in runs:
        a = (today - r["date"]).days
        if 0 <= a < days and r.get("dist"):
            buckets[a] = buckets.get(a, 0.0) + float(r["dist"])
    return [buckets.get(d, 0.0) for d in range(days - 1, -1, -1)]


def ramp_rate(runs: List[dict], ctx: dict) -> List[dict]:
    """Week-over-week volume jump. Distinct from ACWR (7d vs trailing-4wk avg): this compares
    the most recent completed 7 days against the *immediately preceding* 7 days. A single
    abrupt step ≥30% is a classic ramp-rate flag for soft-tissue overload."""
    try:
        today = ctx["today"]
        this_wk = sum((r["dist"] or 0) for r in window(runs, today, 0, 7))
        prev_wk = sum((r["dist"] or 0) for r in window(runs, today, 7, 14))
        if prev_wk < 8 or this_wk < 8:
            return []
        inc = (this_wk - prev_wk) / prev_wk
        if inc < 0.30:
            return []
        pct = int(round(inc * 100))
        return [card(
            "ramp_rate", "warning", "📐", f"주간 거리 한 번에 +{pct}%",
            (f"지난주 {prev_wk:.0f}km에서 이번 주 {this_wk:.0f}km로 한 주 만에 {pct}% 늘었어요. "
             f"보통 주간 증가폭은 10퍼센트 안쪽이 안전선이에요 — 다음 주는 거리를 더 올리기보다 "
             f"지금 양에 몸을 적응시키는 쪽이 부상 위험을 낮춰요."),
            {"this_week_km": round(this_wk, 1), "prev_week_km": round(prev_wk, 1), "increase_pct": pct},
            min(0.9, 0.45 + (inc - 0.30)),
            (f"주간 거리 {prev_wk:.0f}→{this_wk:.0f}km, 한 주 +{pct}% 증가. 10% 룰 관점에서 다음 주 "
             f"완만하게 조절할지, 적응 주간을 둘지 코칭."))]
    except Exception:
        return []


def training_monotony(runs: List[dict], ctx: dict) -> List[dict]:
    """Foster monotony = mean(daily load) / SD(daily load) over the last 14 days."""
    try:
        today = ctx["today"]
        loads = _daily_loads(runs, today, 14)
        active = [x for x in loads if x > 0]
        if len(active) < 6:
            return []
        m = _st.mean(loads)
        sd = _st.pstdev(loads)
        if m <= 0 or sd <= 0:
            return []
        monotony = m / sd
        if monotony < 2.0:
            return []
        rest_days = sum(1 for x in loads if x == 0)
        return [card(
            "training_monotony", "warning", "🔁",
            f"훈련 단조도 {monotony:.1f}, 변화가 너무 적어요",
            (f"최근 2주 일일 부하가 거의 똑같아요(단조도 {monotony:.1f}, 완전 휴식 {rest_days}일). "
             f"매일 비슷한 양을 반복하면 총량이 많지 않아도 몸이 회복할 틈을 못 찾아요. "
             f"가벼운 날은 더 가볍게, 힘든 날은 확실히 힘들게 — 강약을 만들어 주세요."),
            {"monotony": round(monotony, 2), "rest_days": rest_days, "active_days": len(active),
             "mean_km": round(m, 1)},
            min(0.85, 0.4 + (monotony - 2.0) / 2),
            (f"최근 14일 단조도 {monotony:.1f}(휴식 {rest_days}일). 강약 대비를 만들고 진짜 쉬는 날을 "
             f"확보하도록 코칭."))]
    except Exception:
        return []


def training_strain(runs: List[dict], ctx: dict) -> List[dict]:
    """Foster strain = weekly load × monotony over the last 14 days."""
    try:
        today = ctx["today"]
        loads = _daily_loads(runs, today, 14)
        active = [x for x in loads if x > 0]
        if len(active) < 6:
            return []
        m = _st.mean(loads)
        sd = _st.pstdev(loads)
        if m <= 0 or sd <= 0:
            return []
        monotony = m / sd
        weekly = sum((r["dist"] or 0) for r in window(runs, today, 0, 7))
        if weekly < 25 or monotony < 1.8:
            return []
        strain = weekly * monotony
        if strain < 80:
            return []
        return [card(
            "training_strain", "warning", "🥵",
            f"트레이닝 스트레인 {int(round(strain))} 누적",
            (f"이번 주 거리 {weekly:.0f}km에 단조도 {monotony:.1f}가 겹쳐 스트레인이 {int(round(strain))}까지 "
             f"올라갔어요. 양이 많은 주에 변화까지 없으면 피로가 빠르게 쌓여요 — 이번 주 안에 확실히 쉬는 날을 "
             f"하나 넣거나, 다음 주를 회복 주간으로 잡는 걸 추천해요."),
            {"strain": int(round(strain)), "weekly_km": round(weekly, 1), "monotony": round(monotony, 2)},
            min(0.9, 0.45 + (strain - 80) / 200),
            (f"주간 부하 {weekly:.0f}km × 단조도 {monotony:.1f} = 스트레인 {int(round(strain))}. 회복일 배치나 "
             f"다음 주 디로드를 코칭."))]
    except Exception:
        return []


def longest_no_rest_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Longest run of consecutive calendar days with a run and no full rest day."""
    try:
        today = ctx["today"]
        run_days = {r["date"] for r in window(runs, today, -1, 21) if r.get("dist")}
        if not run_days:
            return []
        best = 0
        best_end = None
        cur = 0
        for step in range(0, 22):
            day = today - _dt.timedelta(days=step)
            if day in run_days:
                cur += 1
                if cur > best:
                    best = cur
                    best_end = day
            else:
                cur = 0
        if best < 7:
            return []
        start = best_end - _dt.timedelta(days=best - 1)
        return [card(
            "no_rest_streak", "warning", "📅",
            f"휴식 없이 {best}일 연속 달렸어요",
            (f"{start.isoformat()}부터 {best_end.isoformat()}까지 {best}일간 쉬는 날 없이 이어 달렸어요. "
             f"연속 러닝이 길어지면 근육·힘줄이 회복 신호를 받지 못해 잔부상이 쌓이기 쉬워요. "
             f"주 1회는 완전 휴식이나 크로스 트레이닝으로 비워 두는 게 좋아요."),
            {"streak_days": best, "start": start.isoformat(), "end": best_end.isoformat()},
            min(0.85, 0.4 + (best - 7) * 0.06),
            (f"{best}일 연속 무휴식 러닝({start.isoformat()}~{best_end.isoformat()}). 휴식일·크로스 트레이닝 "
             f"배치를 코칭."))]
    except Exception:
        return []


def hard_easy_polarization(runs: List[dict], ctx: dict) -> List[dict]:
    """Pace-based polarization over the last 28 days."""
    try:
        today = ctx["today"]
        recent = [r for r in window(runs, today, -1, 28) if r.get("pace_s") and r.get("dist")]
        if len(recent) < 8:
            return []
        paces = sorted(r["pace_s"] for r in recent)
        fast = paces[0]
        slow = paces[-1]
        spread = slow - fast
        if spread <= 0:
            return []
        lo = fast + spread * 0.30
        hi = fast + spread * 0.70
        gray = [p for p in paces if lo <= p <= hi]
        gray_frac = len(gray) / len(paces)
        if gray_frac < 0.55:
            return []
        pct = int(round(gray_frac * 100))
        return [card(
            "hard_easy_polarization", "warning", "🎯",
            f"러닝 {pct}%가 어중간한 중간 페이스",
            (f"최근 4주 러닝의 {pct}%가 빠르지도 느리지도 않은 중간 페이스에 몰려 있어요. "
             f"이지런은 더 느긋하게(회복), 포인트 훈련은 더 분명하게 빠르게 — 강약을 가르면 같은 노력으로도 "
             f"자극과 회복을 둘 다 챙길 수 있어요."),
            {"gray_zone_pct": pct, "n_runs": len(recent),
             "fast_pace": fmt_pace(fast), "slow_pace": fmt_pace(slow)},
            min(0.8, 0.35 + (gray_frac - 0.55)),
            (f"최근 28일 러닝 {pct}%가 그레이존 페이스(범위 {fmt_pace(fast)}~{fmt_pace(slow)}/km). 양극화 "
             f"훈련(이지/하드 분리) 의미와 적용을 코칭."))]
    except Exception:
        return []


def consecutive_hard_days(runs: List[dict], ctx: dict) -> List[dict]:
    """Back-to-back hard sessions (tempo/interval, or RPE ≥7) on consecutive calendar days."""
    try:
        today = ctx["today"]
        recent = window(runs, today, -1, 21)
        if not recent:
            return []
        hard_days = set()
        for r in recent:
            is_hard = r.get("type") in _HARD or (r.get("rpe") is not None and r["rpe"] >= 7)
            if is_hard and r.get("dist"):
                hard_days.add(r["date"])
        if len(hard_days) < 2:
            return []
        pairs = 0
        example = None
        for d in sorted(hard_days):
            if (d - _dt.timedelta(days=1)) in hard_days:
                pairs += 1
                if example is None:
                    example = (d - _dt.timedelta(days=1), d)
        if pairs < 1:
            return []
        a, b = example
        return [card(
            "consecutive_hard_days", "warning", "🔥",
            f"고강도 이틀 연속 {pairs}회",
            (f"최근 3주 동안 힘든 훈련을 이틀 연달아 한 경우가 {pairs}번 있었어요"
             f"(예: {a.isoformat()}→{b.isoformat()}). 빠른 적응은 힘든 날 사이에 회복이 끼어야 일어나요 — "
             f"포인트 훈련 다음 날은 이지런이나 휴식으로 비워 두세요."),
            {"hard_back_to_back": pairs, "example_start": a.isoformat(), "example_end": b.isoformat(),
             "hard_days": len(hard_days)},
            min(0.82, 0.42 + pairs * 0.12),
            (f"고강도 연속일 {pairs}회({a.isoformat()}→{b.isoformat()} 등). 하드-이지 배치 원칙으로 "
             f"회복일 끼우기를 코칭."))]
    except Exception:
        return []


def recovery_run_discipline(runs: List[dict], ctx: dict) -> List[dict]:
    """Are recovery/easy runs actually easy?"""
    try:
        today = ctx["today"]
        recent = [r for r in window(runs, today, -1, 28) if r.get("pace_s") and r.get("dist")]
        if len(recent) < 8:
            return []
        easy = [r for r in recent if r.get("type") in ("easy", "recovery")]
        if len(easy) < 4:
            return []
        paces = sorted(r["pace_s"] for r in recent)
        third = max(1, len(paces) // 3)
        fast_ref = _st.median(paces[:third])
        slow_ref = max(paces)
        easy_med = _st.median(r["pace_s"] for r in easy)
        span = slow_ref - fast_ref
        if span <= 0:
            return []
        closeness = (easy_med - fast_ref) / span
        if closeness >= 0.45:
            return []
        gap = int(round(easy_med - fast_ref))
        return [card(
            "recovery_run_discipline", "warning", "🐢",
            f"이지런이 빠른 페이스와 {gap}초 차이뿐",
            (f"최근 4주 이지·회복런 중간 페이스가 {fmt_pace(easy_med)}/km로, 빠른 날 페이스"
             f"({fmt_pace(fast_ref)}/km)와 불과 {gap}초밖에 차이가 안 나요. 회복런이 충분히 느리지 않으면 "
             f"쉬는 효과가 사라지고 피로만 쌓여요 — 회복런은 일부러 더 느긋하게 가도 괜찮아요."),
            {"easy_pace": fmt_pace(easy_med), "fast_pace": fmt_pace(fast_ref), "gap_s": gap,
             "n_easy": len(easy)},
            min(0.78, 0.38 + (0.45 - closeness)),
            (f"이지런 중앙값 {fmt_pace(easy_med)}/km가 빠른 페이스 {fmt_pace(fast_ref)}/km와 {gap}초 차이. "
             f"회복런을 더 느리게 가져가는 의미를 코칭."))]
    except Exception:
        return []


def deload_week(runs: List[dict], ctx: dict) -> List[dict]:
    """Positive deload detection: after a stretch of solid weekly volume, the most recent week
    dropped meaningfully (≥30% below the prior 3-week average)."""
    try:
        today = ctx["today"]
        this_wk = sum((r["dist"] or 0) for r in window(runs, today, 0, 7))
        prior = [
            sum((r["dist"] or 0) for r in window(runs, today, 7, 14)),
            sum((r["dist"] or 0) for r in window(runs, today, 14, 21)),
            sum((r["dist"] or 0) for r in window(runs, today, 21, 28)),
        ]
        prior = [v for v in prior if v > 0]
        if len(prior) < 3:
            return []
        base = _st.mean(prior)
        if base < 20 or this_wk <= 0:
            return []
        drop = (base - this_wk) / base
        if drop < 0.30:
            return []
        pct = int(round(drop * 100))
        return [card(
            "deload_week", "adaptation", "🌙",
            f"이번 주 거리 -{pct}%, 좋은 디로드예요",
            (f"직전 3주 평균 {base:.0f}km/주를 유지하다가 이번 주 {this_wk:.0f}km로 {pct}% 줄였어요. "
             f"이런 의도된 감량 주간은 그동안 쌓인 자극을 실제 체력으로 굳히는 시간이에요 — 거리가 줄었다고 "
             f"불안해할 필요 없어요. 가볍게 움직이고 충분히 자면 다음 주에 더 단단해진 몸으로 돌아와요."),
            {"this_week_km": round(this_wk, 1), "base_km": round(base, 1), "drop_pct": pct},
            min(0.7, 0.35 + (drop - 0.30)),
            (f"3주 평균 {base:.0f}km/주에서 이번 주 {this_wk:.0f}km로 {pct}% 디로드. 회복 적응의 의미를 "
             f"긍정적으로 설명하고 다음 주 복귀 운영을 코칭."))]
    except Exception:
        return []


DETECTORS = [
    ramp_rate,
    training_monotony,
    training_strain,
    longest_no_rest_streak,
    hard_easy_polarization,
    consecutive_hard_days,
    recovery_run_discipline,
    deload_week,
]
