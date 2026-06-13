"""Temporal-pattern insight detectors.

Focus: time-of-week / day-of-week / seasonal patterns derived from run DATES
(``logged_at`` time-of-day is low-trust, so everything here is date-based).
All detectors follow the contract in ``_util`` — date-sorted ``runs`` + ``ctx``,
return 0+ cards, never raise.
"""
from __future__ import annotations

import statistics as _st
from collections import Counter, defaultdict
from typing import List

from insight_detectors._util import card, fmt_pace

_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]
_MONTH_KR = {
    1: "1월", 2: "2월", 3: "3월", 4: "4월", 5: "5월", 6: "6월",
    7: "7월", 8: "8월", 9: "9월", 10: "10월", 11: "11월", 12: "12월",
}
# Month → season (KST, northern hemisphere). 12,1,2 winter / 3,4,5 spring / 6,7,8 summer / 9,10,11 autumn.
_SEASON = {
    12: "겨울", 1: "겨울", 2: "겨울",
    3: "봄", 4: "봄", 5: "봄",
    6: "여름", 7: "여름", 8: "여름",
    9: "가을", 10: "가을", 11: "가을",
}


def fastest_weekday(runs: List[dict], ctx: dict) -> List[dict]:
    """Which day of the week do you run fastest? Compares each weekday's median pace
    (on comparable easy/long efforts) against the overall median."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("pace_s") and r.get("dist") and r["dist"] >= 3
            and r.get("type") in ("easy", "recovery", "long", "tempo")
            and (today - r["date"]).days <= 240]
    if len(pool) < 12:
        return []
    by_wd = defaultdict(list)
    for r in pool:
        by_wd[r["date"].weekday()].append(r["pace_s"])
    # Need at least 3 samples on a weekday to trust its median.
    eligible = {wd: ps for wd, ps in by_wd.items() if len(ps) >= 3}
    if len(eligible) < 3:
        return []
    overall = _st.median([p for ps in eligible.values() for p in ps])
    best_wd = min(eligible, key=lambda wd: _st.median(eligible[wd]))
    best_pace = _st.median(eligible[best_wd])
    delta = overall - best_pace
    if delta < 8:
        return []
    return [card(
        "fastest_weekday", "consistency", "📅",
        f"{_WD_KR[best_wd]}요일에 가장 빨라요 ({fmt_pace(best_pace)}/km)",
        (f"{_WD_KR[best_wd]}요일 러닝 평균이 {fmt_pace(best_pace)}/km로, 전체 평균"
         f"({fmt_pace(overall)}/km)보다 {int(round(delta))}초/km 빠릅니다. "
         f"몸이 가장 잘 받는 요일이라는 뜻이에요 — 중요한 세션을 이 날에 배치해보세요."),
        {"weekday": _WD_KR[best_wd], "best_pace": fmt_pace(best_pace),
         "overall_pace": fmt_pace(overall), "delta_s": int(round(delta)),
         "n": len(eligible[best_wd])},
        min(0.85, 0.4 + delta / 60),
        (f"{_WD_KR[best_wd]}요일 평균 {fmt_pace(best_pace)}/km로 전체 평균 {fmt_pace(overall)}/km보다 "
         f"{int(round(delta))}초/km 빠름. 컨디션 좋은 요일에 핵심 세션 배치하는 운영 코칭."))]


def weekday_vs_weekend_pace(runs: List[dict], ctx: dict) -> List[dict]:
    """Weekday vs weekend pace gap — surfaces whether weekends are your faster/harder days
    or your relaxed long-run days."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("pace_s") and r.get("dist") and r["dist"] >= 3
            and (today - r["date"]).days <= 180]
    if len(pool) < 12:
        return []
    weekday = [r["pace_s"] for r in pool if r["date"].weekday() < 5]
    weekend = [r["pace_s"] for r in pool if r["date"].weekday() >= 5]
    if len(weekday) < 5 or len(weekend) < 5:
        return []
    wd_med = _st.median(weekday)
    we_med = _st.median(weekend)
    gap = abs(wd_med - we_med)
    if gap < 12:
        return []
    if we_med < wd_med:
        faster, slower = "주말", "주중"
        fast_pace, slow_pace = we_med, wd_med
    else:
        faster, slower = "주중", "주말"
        fast_pace, slow_pace = wd_med, we_med
    return [card(
        "weekday_vs_weekend_pace", "consistency", "🗓️",
        f"{faster} 러닝이 {int(round(gap))}초/km 더 빨라요",
        (f"{faster} 평균 {fmt_pace(fast_pace)}/km, {slower} 평균 {fmt_pace(slow_pace)}/km로 "
         f"{int(round(gap))}초/km 차이가 납니다. {faster}에 강도 높은 러닝이 몰려 있다는 신호예요 — "
         f"강·약 배분이 의도한 대로인지 한 번 점검해보세요."),
        {"weekday_pace": fmt_pace(wd_med), "weekend_pace": fmt_pace(we_med),
         "gap_s": int(round(gap)), "faster": faster,
         "n_weekday": len(weekday), "n_weekend": len(weekend)},
        min(0.75, 0.35 + gap / 70),
        (f"{faster} {fmt_pace(fast_pace)}/km vs {slower} {fmt_pace(slow_pace)}/km, {int(round(gap))}초/km 차이. "
         f"주중·주말 강도 배분 의도 점검 코칭."))]


def seasonal_pace_shift(runs: List[dict], ctx: dict) -> List[dict]:
    """Seasonal pace change (temperature proxy via month) — e.g. summer heat slows you down,
    cooler months speed you up. Compares the two best-sampled seasons."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("pace_s") and r.get("dist") and r["dist"] >= 3
            and r.get("type") in ("easy", "recovery", "long")
            and (today - r["date"]).days <= 400]
    if len(pool) < 16:
        return []
    by_season = defaultdict(list)
    for r in pool:
        by_season[_SEASON[r["date"].month]].append(r["pace_s"])
    eligible = {s: ps for s, ps in by_season.items() if len(ps) >= 5}
    if len(eligible) < 2:
        return []
    fast_season = min(eligible, key=lambda s: _st.median(eligible[s]))
    slow_season = max(eligible, key=lambda s: _st.median(eligible[s]))
    if fast_season == slow_season:
        return []
    fast_pace = _st.median(eligible[fast_season])
    slow_pace = _st.median(eligible[slow_season])
    delta = slow_pace - fast_pace
    if delta < 12:
        return []
    return [card(
        "seasonal_pace_shift", "adaptation", "🌡️",
        f"{fast_season}이 {slow_season}보다 {int(round(delta))}초/km 빨라요",
        (f"{fast_season} 이지런 평균은 {fmt_pace(fast_pace)}/km인데 {slow_season}엔 {fmt_pace(slow_pace)}/km로 "
         f"{int(round(delta))}초/km 느려집니다. 기온 영향이 큰 패턴이에요 — "
         f"더운 계절엔 페이스보다 심박·체감 강도로 조절하는 게 맞아요."),
        {"fast_season": fast_season, "slow_season": slow_season,
         "fast_pace": fmt_pace(fast_pace), "slow_pace": fmt_pace(slow_pace),
         "delta_s": int(round(delta)),
         "n_fast": len(eligible[fast_season]), "n_slow": len(eligible[slow_season])},
        min(0.8, 0.35 + delta / 80),
        (f"{fast_season} {fmt_pace(fast_pace)}/km vs {slow_season} {fmt_pace(slow_pace)}/km, {int(round(delta))}초/km 차이. "
         f"기온 프록시 기반 계절 페이스 변화 — 더운 계절 심박 기준 조절 코칭."))]


def most_active_month(runs: List[dict], ctx: dict) -> List[dict]:
    """Your biggest training month by volume (last ~12 months) vs the monthly average —
    rewards a standout block of work."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("dist") and (today - r["date"]).days <= 370]
    if len(pool) < 12:
        return []
    by_month = defaultdict(float)
    for r in pool:
        key = (r["date"].year, r["date"].month)
        by_month[key] += r["dist"]
    # Drop the current (likely partial) month so it does not skew the peak.
    cur = (today.year, today.month)
    full = {k: v for k, v in by_month.items() if k != cur}
    if len(full) < 3:
        return []
    peak_key = max(full, key=lambda k: full[k])
    peak_km = full[peak_key]
    avg_km = _st.mean(full.values())
    if avg_km <= 0 or peak_km < avg_km * 1.4 or peak_km < 40:
        return []
    pct = int(round((peak_km / avg_km - 1) * 100))
    label = _MONTH_KR[peak_key[1]]
    return [card(
        "most_active_month", "consistency", "🏔️",
        f"{peak_key[0]}년 {label}, {int(round(peak_km))}km로 최다",
        (f"{peak_key[0]}년 {label}에 {int(round(peak_km))}km를 달려 월 평균"
         f"({int(round(avg_km))}km)보다 {pct}% 많은, 가장 많이 달린 달이었어요. "
         f"이 시기에 무엇이 잘 굴러갔는지 떠올려보면 다음 빌드업의 힌트가 됩니다."),
        {"month": label, "year": peak_key[0], "month_km": int(round(peak_km)),
         "avg_km": int(round(avg_km)), "pct_over_avg": pct},
        min(0.7, 0.3 + (peak_km / avg_km - 1.4) / 2),
        (f"{peak_key[0]}년 {label} {int(round(peak_km))}km로 월평균 {int(round(avg_km))}km 대비 {pct}% 최다. "
         f"잘 굴러간 요인 회고 + 다음 빌드업 적용 코칭."))]


def weekday_distance_distribution(runs: List[dict], ctx: dict) -> List[dict]:
    """Where the mileage lives across the week — flags one day that carries an outsized
    share of total distance (typically the long-run day)."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("dist") and (today - r["date"]).days <= 180]
    if len(pool) < 12:
        return []
    by_wd = defaultdict(float)
    for r in pool:
        by_wd[r["date"].weekday()] += r["dist"]
    total = sum(by_wd.values())
    active_days = len(by_wd)
    if total <= 0 or active_days < 3:
        return []
    top_wd = max(by_wd, key=lambda wd: by_wd[wd])
    top_km = by_wd[top_wd]
    share = top_km / total
    even_share = 1.0 / active_days
    # Only surface when one day clearly dominates relative to an even spread.
    if share < 0.30 or share < even_share * 1.6:
        return []
    pct = int(round(share * 100))
    return [card(
        "weekday_distance_distribution", "consistency", "📊",
        f"전체 거리의 {pct}%가 {_WD_KR[top_wd]}요일에 몰려요",
        (f"최근 6개월 누적 거리 중 {pct}%({int(round(top_km))}km)가 {_WD_KR[top_wd]}요일에 집중돼 있어요. "
         f"롱런을 이 날 고정해 둔 패턴인데, 주중 거리가 너무 얇지 않은지 함께 보면 좋아요."),
        {"weekday": _WD_KR[top_wd], "share_pct": pct, "weekday_km": int(round(top_km)),
         "total_km": int(round(total)), "active_days": active_days},
        min(0.65, 0.3 + (share - even_share)),
        (f"{_WD_KR[top_wd]}요일에 누적 거리의 {pct}% 집중({int(round(top_km))}km/{int(round(total))}km). "
         f"롱런 요일 고정 패턴 + 주중 볼륨 균형 점검 코칭."))]


def preferred_run_day(runs: List[dict], ctx: dict) -> List[dict]:
    """Most frequent training day — a habit/rhythm signal. Flags the weekday you show up on
    most often relative to an even spread."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("dist") and (today - r["date"]).days <= 120]
    if len(pool) < 12:
        return []
    counts = Counter(r["date"].weekday() for r in pool)
    if len(counts) < 3:
        return []
    top_wd, top_n = counts.most_common(1)[0]
    total = sum(counts.values())
    share = top_n / total
    even_share = 1.0 / len(counts)
    if top_n < 4 or share < even_share * 1.5:
        return []
    pct = int(round(share * 100))
    return [card(
        "preferred_run_day", "consistency", "🔁",
        f"가장 자주 달리는 날은 {_WD_KR[top_wd]}요일 ({top_n}회)",
        (f"최근 4개월 러닝의 {pct}%가 {_WD_KR[top_wd]}요일이었어요({top_n}회). "
         f"고정된 러닝 요일이 있다는 건 습관이 자리 잡았다는 뜻 — 이 앵커를 중심으로 주간 계획을 짜면 흔들리지 않아요."),
        {"weekday": _WD_KR[top_wd], "count": top_n, "share_pct": pct,
         "total_runs": total},
        min(0.6, 0.3 + (share - even_share)),
        (f"{_WD_KR[top_wd]}요일에 러닝 {top_n}회({pct}%) 집중, 루틴 앵커. "
         f"고정 요일 중심 주간 계획 설계 코칭."))]


def quietest_weekday(runs: List[dict], ctx: dict) -> List[dict]:
    """The day you almost never run — surfaces a structural gap in the week that could be
    a planned rest day or an unintended hole."""
    today = ctx["today"]
    pool = [r for r in runs
            if r.get("dist") and (today - r["date"]).days <= 120]
    if len(pool) < 14:
        return []
    counts = Counter(r["date"].weekday() for r in pool)
    # Require coverage across most of the week so a 'quiet' day is meaningful.
    if len(counts) < 5:
        return []
    weeks = max(1, ((today - min(r["date"] for r in pool)).days + 1) / 7.0)
    quiet_wd = min(range(7), key=lambda wd: counts.get(wd, 0))
    quiet_n = counts.get(quiet_wd, 0)
    busiest_n = max(counts.values())
    # Only flag a genuinely sparse day relative to a busy one and to the number of weeks.
    if busiest_n < 4 or quiet_n > max(1, weeks * 0.2) or quiet_n >= busiest_n * 0.4:
        return []
    return [card(
        "quietest_weekday", "consistency", "🌙",
        f"{_WD_KR[quiet_wd]}요일엔 거의 안 달려요 ({quiet_n}회)",
        (f"최근 약 {int(round(weeks))}주 동안 {_WD_KR[quiet_wd]}요일 러닝은 {quiet_n}회뿐이에요. "
         f"의도한 휴식일이면 좋은 리듬이고, 아니라면 가벼운 회복 조깅 한 칸을 넣을 여지가 있는 자리예요."),
        {"weekday": _WD_KR[quiet_wd], "count": quiet_n, "weeks": int(round(weeks)),
         "busiest_count": busiest_n},
        min(0.55, 0.28 + (busiest_n - quiet_n) / 20),
        (f"{_WD_KR[quiet_wd]}요일 러닝 {quiet_n}회로 주간 최소. "
         f"의도된 휴식일인지 / 회복 조깅 추가 여지인지 함께 점검하는 코칭."))]


DETECTORS = [
    fastest_weekday,
    weekday_vs_weekend_pace,
    seasonal_pace_shift,
    most_active_month,
    weekday_distance_distribution,
    preferred_run_day,
    quietest_weekday,
]
