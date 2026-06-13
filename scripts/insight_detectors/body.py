"""Body composition insight detectors — weight trend, race-weight progress, fueling signals.

Focus: weight-trend / power-to-weight / under-fueling / stable-weight-volume-up adaptation.
Requires ``ctx["body"]`` (injected by ``insights._build_ctx``). If absent, all detectors
return []. Follows the detector/card contract in ``_util``.
"""
from __future__ import annotations

from typing import List

from insight_detectors._util import card, fmt_pace, window, mean


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _week_km(runs: List[dict], today, lo: int, hi: int) -> float:
    """Total distance (km) in the window (lo, hi] days ago."""
    return sum((r["dist"] or 0) for r in window(runs, today, lo, hi) if r.get("dist"))


def _easy_pace_mean(runs: List[dict], today, lo: int, hi: int):
    """Mean pace_s for easy/long/recovery runs in window. None if no data."""
    paces = [
        r["pace_s"] for r in window(runs, today, lo, hi)
        if r.get("pace_s") and r.get("type") in ("easy", "long", "recovery")
    ]
    return mean(paces)


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------

def detect_race_weight_progress(runs: List[dict], ctx: dict) -> List[dict]:
    """Race-weight gap and on-track status. Surfaces when a race-weight target is set and
    weeks_left is known. Celebrates on-track progress; warns about unsafe pace."""
    try:
        body = ctx.get("body")
        if not body:
            return []
        rw = body.get("race_weight")
        if not rw:
            return []
        weeks_left = rw.get("weeks_left")
        if weeks_left is None:
            return []

        current_kg = rw.get("current_kg")
        target_kg = rw.get("target_kg")
        gap_kg = rw.get("gap_kg")       # negative = needs to lose
        on_track = rw.get("on_track", False)
        safe = rw.get("safe", True)

        if current_kg is None or target_kg is None or gap_kg is None:
            return []

        # urgency increases as race approaches
        score = max(0.3, min(0.95, 1.0 - weeks_left / 20.0))

        if not safe:
            return [card(
                "body_race_weight_unsafe", "warning", "⚖️",
                f"감량 페이스 주의 · 주 {abs(rw.get('weekly_needed_kg_wk', 0)):.2f}kg",
                (f"레이스까지 {weeks_left:.0f}주 남은 시점에 목표 {target_kg:.1f}kg까지 "
                 f"{abs(gap_kg):.1f}kg을 빼려면 주당 "
                 f"{abs(rw.get('weekly_needed_kg_wk', 0)):.2f}kg 감량이 필요해요. "
                 "이 속도는 무리한 감량 페이스로, 훈련 퍼포먼스와 건강에 영향을 줄 수 있어요."),
                {"current_kg": round(current_kg, 1), "target_kg": round(target_kg, 1),
                 "gap_kg": round(gap_kg, 1), "weeks_left": round(weeks_left, 1),
                 "weekly_needed": round(rw.get("weekly_needed_kg_wk", 0), 3)},
                min(0.9, score + 0.1),
                (f"목표 {target_kg:.1f}kg까지 {abs(gap_kg):.1f}kg, {weeks_left:.0f}주 남음. "
                 "안전한 감량 속도와 영양 전략을 코칭."))]

        # safe path — celebrate on_track or show gap
        if on_track:
            return [card(
                "body_race_weight", "improvement", "⚖️",
                f"레이스까지 {target_kg:.1f}kg 목표 · 순조로워요",
                (f"현재 {current_kg:.1f}kg에서 목표 {target_kg:.1f}kg까지 {abs(gap_kg):.1f}kg 남았고, "
                 f"현재 감량 페이스면 레이스({weeks_left:.0f}주 후)까지 충분히 도달할 수 있어요."),
                {"current_kg": round(current_kg, 1), "target_kg": round(target_kg, 1),
                 "gap_kg": round(gap_kg, 1), "weeks_left": round(weeks_left, 1)},
                score,
                (f"현재 {current_kg:.1f}kg, 목표 {target_kg:.1f}kg({abs(gap_kg):.1f}kg 차), "
                 f"{weeks_left:.0f}주 남음, 순조로운 진행. 체중 관리 + 훈련 밸런스 코칭."))]
        else:
            # behind pace but safe — mild nudge
            return [card(
                "body_race_weight", "improvement", "⚖️",
                f"레이스까지 {target_kg:.1f}kg 목표 · 현재 {current_kg:.1f}kg({gap_kg:+.1f})",
                (f"레이스까지 {weeks_left:.0f}주, 목표 {target_kg:.1f}kg까지 {abs(gap_kg):.1f}kg 남았어요. "
                 "현재 페이스를 조금 더 일관되게 가져가면 도달할 수 있어요."),
                {"current_kg": round(current_kg, 1), "target_kg": round(target_kg, 1),
                 "gap_kg": round(gap_kg, 1), "weeks_left": round(weeks_left, 1)},
                max(0.3, score - 0.1),
                (f"현재 {current_kg:.1f}kg, 목표 {target_kg:.1f}kg({abs(gap_kg):.1f}kg 차), "
                 f"{weeks_left:.0f}주 남음, 약간 뒤처짐. 식단·훈련 조정 코칭."))]
    except Exception:
        return []


def detect_weight_down_pace_up(runs: List[dict], ctx: dict) -> List[dict]:
    """Power-to-weight win: losing weight while easy/all-run pace is improving. Compares
    recent 4 weeks vs preceding 4 weeks (easy+long pace) alongside a negative weight trend."""
    try:
        body = ctx.get("body")
        if not body:
            return []
        trend = body.get("trend")
        if not trend:
            return []
        rate = trend.get("rate_kg_wk")
        if rate is None or rate >= -0.05:   # not meaningfully losing
            return []

        today = ctx["today"]
        recent_pace = _easy_pace_mean(runs, today, 0, 28)
        base_pace = _easy_pace_mean(runs, today, 28, 56)
        if recent_pace is None or base_pace is None:
            return []
        # pace improvement = base slower than recent (higher sec/km = slower)
        pace_gain = base_pace - recent_pace   # positive = got faster
        if pace_gain < 5:                     # at least 5 sec/km improvement
            return []
        weight_lost = abs(rate * 4)           # ~kg lost over 4 weeks
        if weight_lost < 0.3:
            return []

        score = min(0.9, 0.55 + pace_gain / 120 + weight_lost / 4)
        return [card(
            "body_weight_down_pace_up", "improvement", "🪶",
            f"체중 -{weight_lost:.1f}kg + 페이스 -{int(round(pace_gain))}초/km",
            (f"최근 4주간 체중이 약 {weight_lost:.1f}kg 줄면서 이지런 평균 페이스도 "
             f"{int(round(pace_gain))}초/km 빨라졌어요. 파워-투-웨이트 비가 실제로 올라가고 있어요."),
            {"weight_lost_kg": round(weight_lost, 1), "pace_gain_s": int(round(pace_gain)),
             "rate_kg_wk": round(rate, 3),
             "recent_pace": fmt_pace(recent_pace), "base_pace": fmt_pace(base_pace)},
            score,
            (f"4주간 -{weight_lost:.1f}kg & 이지 페이스 -{int(round(pace_gain))}초/km. "
             "파워-투-웨이트 개선이 기록에 어떻게 연결되는지 코칭."))]
    except Exception:
        return []


def detect_under_fueling(runs: List[dict], ctx: dict) -> List[dict]:
    """Under-fueling / rapid-weight-loss warning. High priority (score 0.8+) — health signal."""
    try:
        body = ctx.get("body")
        if not body:
            return []
        uf = body.get("under_fueling_risk")
        if not uf:
            return []
        rate = uf.get("rate_kg_wk")
        pct = uf.get("pct_per_week")
        msg = uf.get("msg") or "빠른 체중 감소가 감지됐어요."
        if rate is None or pct is None:
            return []

        score = min(0.95, 0.80 + abs(pct) / 10)
        return [card(
            "body_under_fueling", "warning", "⚠️",
            f"주 {pct:.1f}% 빠른 체중 감소 · 에너지 부족 신호",
            msg,
            {"rate_kg_wk": round(rate, 3), "pct_per_week": round(pct, 2)},
            score,
            (f"주간 -{pct:.1f}% 체중 감소({rate:.3f}kg/주). 에너지 가용성 확인과 적정 칼로리 섭취 코칭."))]
    except Exception:
        return []


def detect_stable_weight_volume_up(runs: List[dict], ctx: dict) -> List[dict]:
    """Adaptation signal: weight stable (±0.2 kg/week) while training volume is meaningfully
    increasing (≥10% recent 4 weeks vs prior 4 weeks). Body is adapting efficiently."""
    try:
        body = ctx.get("body")
        if not body:
            return []
        trend = body.get("trend")
        if not trend:
            return []
        rate = trend.get("rate_kg_wk")
        if rate is None or abs(rate) > 0.2:   # not stable
            return []

        today = ctx["today"]
        recent_vol = _week_km(runs, today, 0, 28)
        base_vol = _week_km(runs, today, 28, 56)
        if base_vol < 5 or recent_vol < 5:
            return []
        vol_inc = (recent_vol - base_vol) / base_vol
        if vol_inc < 0.10:    # less than 10% increase
            return []

        pct = int(round(vol_inc * 100))
        score = min(0.85, 0.50 + vol_inc / 2)
        return [card(
            "body_stable_weight_volume_up", "adaptation", "📈",
            f"체중 유지하며 볼륨 +{pct}%",
            (f"최근 4주 훈련량이 {recent_vol:.0f}km로 이전 4주({base_vol:.0f}km)보다 {pct}% 늘었는데도 "
             f"체중은 주당 {abs(rate):.2f}kg 이내로 안정적이에요. 몸이 높아진 부하에 잘 적응하고 있어요."),
            {"recent_vol_km": round(recent_vol, 1), "base_vol_km": round(base_vol, 1),
             "vol_inc_pct": pct, "rate_kg_wk": round(rate, 3)},
            score,
            (f"볼륨 {base_vol:.0f}→{recent_vol:.0f}km(+{pct}%) + 체중 안정. "
             "적응 신호의 의미와 다음 단계 훈련 계획 코칭."))]
    except Exception:
        return []


DETECTORS = [
    detect_race_weight_progress,
    detect_weight_down_pace_up,
    detect_under_fueling,
    detect_stable_weight_volume_up,
]
