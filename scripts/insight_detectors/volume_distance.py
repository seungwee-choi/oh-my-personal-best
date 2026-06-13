"""Volume & distance trend detectors.

Focus: weekly/monthly volume trends, longest streak of rising weeks, average run
distance trend, this-month distance vs personal average, distance-distribution shift
(long-run share rising). Distance/pace/time/ascent coverage is ~99%, so these are
distance-based and safe. Avoids core/records ids and metrics (load_spike, pr_longest,
consistency_weeks, etc.). Follows the detector/card contract in ``_util``.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from collections import Counter
from typing import List

from insight_detectors._util import card, fmt_pace, window, mean


def _week_key(d):
    return d.isocalendar()[:2]


def _weekly_volumes(runs, today, n_weeks):
    """Returns list of (week_index, km) for the last ``n_weeks`` completed/current weeks,
    ordered most-recent-first. week_index 0 = current week."""
    by_week: Counter = Counter()
    for r in runs:
        if r.get("dist"):
            by_week[_week_key(r["date"])] += r["dist"]
    out = []
    for step in range(n_weeks):
        wk = _week_key(today - _dt.timedelta(days=7 * step))
        out.append((step, by_week.get(wk, 0.0)))
    return out


def weekly_volume_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Recent 4 full weeks of volume vs the 4 weeks before that — a monthly volume ramp.
    Uses weeks 1-4 (fully elapsed) so the in-progress current week never distorts it."""
    try:
        today = ctx["today"]
        wk = _weekly_volumes(runs, today, 9)  # week 0 (current) + weeks 1..8
        recent = [v for i, v in wk if 1 <= i <= 4]
        base = [v for i, v in wk if 5 <= i <= 8]
        if len([v for v in recent if v > 0]) < 3 or len([v for v in base if v > 0]) < 3:
            return []
        r_avg, b_avg = _st.mean(recent), _st.mean(base)
        if b_avg <= 0:
            return []
        gain = r_avg - b_avg
        pct = gain / b_avg * 100
        if pct < 12 or gain < 5:
            return []
        return [card(
            "weekly_volume_trend", "improvement", "📊",
            f"주간 거리 +{int(round(pct))}%",
            (f"최근 4주 평균 주간 거리가 {r_avg:.0f}km로, 그 전 4주({b_avg:.0f}km/주)보다 "
             f"{int(round(pct))}% 늘었어요. 무리한 한 주가 아니라 한 달 단위로 볼륨이 자리잡았다는 신호예요."),
            {"recent_avg_km": round(r_avg, 1), "base_avg_km": round(b_avg, 1),
             "gain_pct": int(round(pct))},
            min(0.85, 0.4 + pct / 120),
            (f"최근 4주 평균 {r_avg:.0f}km/주, 직전 4주 {b_avg:.0f}km/주 대비 {int(round(pct))}% 증가. "
             f"볼륨이 안정적으로 올라온 의미와 다음 한 달 운영 코칭."))]
    except Exception:
        return []


def rising_weeks_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Longest run of consecutive fully-elapsed weeks where weekly volume increased
    week-over-week. Rewards a sustained build block, distinct from a single load spike."""
    try:
        today = ctx["today"]
        wk = _weekly_volumes(runs, today, 11)  # current + 10 prior
        vols = [v for i, v in wk if i >= 1]  # skip in-progress current week, oldest last
        vols = list(reversed(vols))  # chronological: oldest -> newest
        if len([v for v in vols if v > 0]) < 4:
            return []
        best = cur = 0
        best_start = best_end = 0
        for j in range(1, len(vols)):
            if vols[j] > vols[j - 1] and vols[j - 1] > 0:
                cur += 1
                if cur > best:
                    best, best_end = cur, j
                    best_start = j - cur
            else:
                cur = 0
        if best < 3:
            return []
        weeks = best + 1
        lo, hi = vols[best_start], vols[best_end]
        if hi <= lo:
            return []
        return [card(
            "rising_weeks_streak", "consistency", "📈",
            f"{best}주 연속 거리 증가",
            (f"주간 거리가 {best}주 연속으로 늘었어요({lo:.0f}km에서 {hi:.0f}km/주까지). "
             f"점진적으로 쌓아 올리는 빌드업은 부상 없이 체력을 키우는 가장 좋은 방식이에요."),
            {"rising_weeks": best, "from_km": round(lo, 1), "to_km": round(hi, 1)},
            min(0.85, 0.42 + best / 14),
            (f"{best}주 연속 주간 거리 증가({lo:.0f}→{hi:.0f}km/주). 빌드업 칭찬과 "
             f"디로드(감량 주) 타이밍 코칭."))]
    except Exception:
        return []


def avg_run_distance_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Average distance PER RUN is trending up — runs are getting longer on average,
    independent of how many you do. Recent ~5 weeks vs 8-18 weeks ago."""
    try:
        today = ctx["today"]
        recent = [r["dist"] for r in window(runs, today, -1, 35) if r.get("dist")]
        base = [r["dist"] for r in window(runs, today, 56, 126) if r.get("dist")]
        if len(recent) < 4 or len(base) < 5:
            return []
        r_avg, b_avg = _st.mean(recent), _st.mean(base)
        gain = r_avg - b_avg
        if b_avg <= 0:
            return []
        pct = gain / b_avg * 100
        if gain < 1.0 or pct < 12:
            return []
        return [card(
            "avg_run_distance_trend", "improvement", "📏",
            f"한 번에 평균 {r_avg:.1f}km",
            (f"요즘 한 번 나갈 때 평균 {r_avg:.1f}km를 달려요. 두세 달 전 평균({b_avg:.1f}km)보다 "
             f"{gain:.1f}km 길어졌어요 — 같은 횟수라도 한 번의 자극이 더 커진 거예요."),
            {"recent_avg_km": round(r_avg, 1), "base_avg_km": round(b_avg, 1),
             "delta_km": round(gain, 1), "n_recent": len(recent)},
            min(0.8, 0.4 + pct / 110),
            (f"런당 평균 거리 {b_avg:.1f}→{r_avg:.1f}km 상승. 단일 세션 자극이 커진 의미와 "
             f"회복 균형 코칭."))]
    except Exception:
        return []


def month_distance_vs_avg(runs: List[dict], ctx: dict) -> List[dict]:
    """This calendar month's total distance vs the runner's typical month (avg of prior
    full calendar months with any running). Surfaces a record-setting or near-record month."""
    try:
        today = ctx["today"]
        by_month: Counter = Counter()
        for r in runs:
            if r.get("dist"):
                by_month[(r["date"].year, r["date"].month)] += r["dist"]
        cur_key = (today.year, today.month)
        cur = by_month.get(cur_key, 0.0)
        prior = [v for k, v in by_month.items() if k != cur_key and v > 0]
        if cur <= 0 or len(prior) < 3:
            return []
        avg = _st.mean(prior)
        if avg <= 0:
            return []
        # days elapsed in current month -> pace projection for context
        elapsed = today.day
        pct_of_avg = cur / avg * 100
        # require already at/above typical month even before month ends
        if pct_of_avg < 105:
            return []
        proj = cur / max(elapsed, 1) * 30.0
        return [card(
            "month_distance_vs_avg", "pr", "🗓️",
            f"이번 달 {cur:.0f}km, 평소의 {int(round(pct_of_avg))}%",
            (f"이번 달 누적 {cur:.0f}km로, 평소 한 달 평균({avg:.0f}km)을 이미 {int(round(pct_of_avg - 100))}% "
             f"넘었어요. 이 페이스면 {proj:.0f}km로 마무리될 흐름이에요."),
            {"month_km": round(cur, 1), "avg_month_km": round(avg, 1),
             "pct_of_avg": int(round(pct_of_avg)), "projected_km": round(proj),
             "elapsed_days": elapsed},
            min(0.85, 0.45 + (pct_of_avg - 105) / 150),
            (f"이번 달 {cur:.0f}km(평소 {avg:.0f}km/월의 {int(round(pct_of_avg))}%). "
             f"기록적인 달의 의미와 후반부 페이싱/회복 코칭."))]
    except Exception:
        return []


def long_run_share_shift(runs: List[dict], ctx: dict) -> List[dict]:
    """Distribution shift: long runs (>=13km) now make up a bigger share of total volume
    than before. Signals an endurance-oriented mix, not just more total km."""
    try:
        today = ctx["today"]
        LONG = 13.0

        def share(lo, hi):
            seg = [r["dist"] for r in window(runs, today, lo, hi) if r.get("dist")]
            tot = sum(seg)
            if tot <= 0 or len(seg) < 4:
                return None, tot, len(seg)
            longs = sum(d for d in seg if d >= LONG)
            return longs / tot, tot, len(seg)

        r_share, r_tot, r_n = share(-1, 42)
        b_share, b_tot, b_n = share(56, 140)
        if r_share is None or b_share is None:
            return []
        delta = (r_share - b_share) * 100
        if r_share < 0.25 or delta < 12:
            return []
        return [card(
            "long_run_share_shift", "adaptation", "🛣️",
            f"롱런 비중 {int(round(r_share * 100))}%로 상승",
            (f"전체 거리에서 롱런(13km+)이 차지하는 비중이 {int(round(b_share * 100))}%에서 "
             f"{int(round(r_share * 100))}%로 올랐어요. 단순히 더 뛰는 게 아니라 지구력 쪽으로 "
             f"훈련 무게중심이 옮겨갔다는 뜻이에요."),
            {"recent_share_pct": int(round(r_share * 100)), "base_share_pct": int(round(b_share * 100)),
             "delta_pct": int(round(delta)), "n_recent": r_n},
            min(0.8, 0.4 + delta / 90),
            (f"롱런(13km+) 비중 {int(round(b_share * 100))}→{int(round(r_share * 100))}%로 상승. "
             f"지구력 지향 믹스 변화 의미와 목표 정합성 코칭."))]
    except Exception:
        return []


def monthly_volume_record(runs: List[dict], ctx: dict) -> List[dict]:
    """A fully-completed recent month set a new monthly-volume high vs all prior full
    months. Distinct from the in-progress month check above."""
    try:
        today = ctx["today"]
        by_month: Counter = Counter()
        for r in runs:
            if r.get("dist"):
                by_month[(r["date"].year, r["date"].month)] += r["dist"]
        cur_key = (today.year, today.month)
        full = {k: v for k, v in by_month.items() if k != cur_key and v > 0}
        if len(full) < 4:
            return []
        # most recent fully completed month
        last_key = max(full.keys())
        # only fire if it's genuinely recent (within ~45 days)
        last_month_end = _dt.date(last_key[0], last_key[1], 28)
        if (today - last_month_end).days > 50:
            return []
        last_val = full[last_key]
        others = [v for k, v in full.items() if k != last_key]
        if not others:
            return []
        prev_best = max(others)
        if last_val <= prev_best:
            return []
        gain = last_val - prev_best
        if gain < 5:
            return []
        return [card(
            "monthly_volume_record", "pr", "🏆",
            f"월 최고 거리 {last_val:.0f}km",
            (f"{last_key[1]}월에 {last_val:.0f}km를 달려 역대 가장 많이 뛴 달을 새로 썼어요"
             f"(이전 최고 {prev_best:.0f}km). 한 달 단위 지구력 기반이 확실히 넓어졌어요."),
            {"month": f"{last_key[0]}-{last_key[1]:02d}", "month_km": round(last_val, 1),
             "prev_best_km": round(prev_best, 1), "gain_km": round(last_val - prev_best, 1)},
            min(0.9, 0.5 + (last_val - prev_best) / 60),
            (f"{last_key[1]}월 {last_val:.0f}km로 월 최고 거리 경신(이전 {prev_best:.0f}km). "
             f"성취 의미와 다음 달 무리 없는 유지 코칭."))]
    except Exception:
        return []


def volume_drop_warning(runs: List[dict], ctx: dict) -> List[dict]:
    """Hidden de-training risk: recent 3 full weeks of volume well below the established
    base (weeks 4-9), after a real base existed. A gentle nudge, not an alarm."""
    try:
        today = ctx["today"]
        wk = _weekly_volumes(runs, today, 10)
        recent = [v for i, v in wk if 1 <= i <= 3]
        base = [v for i, v in wk if 4 <= i <= 9]
        base_active = [v for v in base if v > 0]
        if len(base_active) < 4:
            return []
        r_avg = _st.mean(recent) if recent else 0.0
        b_avg = _st.mean(base_active)
        if b_avg < 10:  # no meaningful base to drop from
            return []
        drop = (b_avg - r_avg) / b_avg * 100
        if drop < 35:
            return []
        return [card(
            "volume_drop_warning", "warning", "📉",
            f"최근 주간 거리 -{int(round(drop))}%",
            (f"최근 3주 평균 주간 거리가 {r_avg:.0f}km로, 그 전 기준({b_avg:.0f}km/주)보다 "
             f"{int(round(drop))}% 줄었어요. 의도한 감량이면 좋지만, 아니라면 짧게라도 다시 리듬을 "
             f"잡는 게 그동안 쌓은 체력을 지키는 길이에요."),
            {"recent_avg_km": round(r_avg, 1), "base_avg_km": round(b_avg, 1),
             "drop_pct": int(round(drop))},
            min(0.75, 0.35 + (drop - 35) / 120),
            (f"최근 3주 평균 {r_avg:.0f}km/주, 기준 {b_avg:.0f}km/주 대비 {int(round(drop))}% 감소. "
             f"의도된 디로드인지 확인하고 디트레이닝 방지 운영 코칭."))]
    except Exception:
        return []


DETECTORS = [
    weekly_volume_trend,
    rising_weeks_streak,
    avg_run_distance_trend,
    month_distance_vs_avg,
    long_run_share_shift,
    monthly_volume_record,
    volume_drop_warning,
]
