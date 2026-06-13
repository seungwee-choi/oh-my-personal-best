"""Consistency & rhythm detectors: daily streaks, all-time longest streak, weeks hitting
target_km in a row, no-rest-week (ran every week) streaks, return after a gap, weekend
long-run habit. Distinct from core ``consistency_weeks`` (which counts weeks with >=3 runs)."""
from __future__ import annotations

import datetime as _dt
from collections import Counter, defaultdict
from typing import List

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


def _run_dates(runs: List[dict]) -> List[_dt.date]:
    """Unique run dates (a run = any logged session with a date), sorted ascending."""
    seen = {r["date"] for r in runs if r.get("date") is not None}
    return sorted(seen)


def daily_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Current consecutive-day running streak ending at/near today."""
    today = ctx.get("today")
    if today is None:
        return []
    dates = set(_run_dates(runs))
    if not dates:
        return []
    if today in dates:
        anchor = today
    elif (today - _dt.timedelta(days=1)) in dates:
        anchor = today - _dt.timedelta(days=1)
    else:
        return []
    streak = 0
    d = anchor
    while d in dates:
        streak += 1
        d -= _dt.timedelta(days=1)
    if streak < 5:
        return []
    km = sum((r["dist"] or 0) for r in runs
             if r.get("date") is not None and anchor - _dt.timedelta(days=streak - 1) <= r["date"] <= anchor)
    return [card(
        "daily_streak", "consistency", "🗓️", f"{streak}일 연속 러닝",
        (f"{streak}일 동안 하루도 안 빠지고 달렸어요. 이 기간 누적 {km:.0f}km — 매일 신발 끈을 묶는 "
         f"습관 자체가 가장 단단한 기초 체력이에요."),
        {"days": streak, "km": round(km, 1), "anchor": anchor.isoformat()},
        min(0.9, 0.45 + streak / 30),
        f"{streak}일 연속 러닝 진행 중(누적 {km:.0f}km). 매일 달리기의 의미와 회복일 배치 코칭.")]


def longest_daily_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """All-time longest consecutive-day running streak."""
    today = ctx.get("today")
    if today is None:
        return []
    dates = _run_dates(runs)
    if len(dates) < 7:
        return []
    best = 0
    best_end = None
    cur = 0
    cur_start = None
    prev = None
    for d in dates:
        if prev is not None and (d - prev).days == 1:
            cur += 1
        else:
            cur = 1
            cur_start = d
        if cur > best:
            best = cur
            best_end = d
        prev = d
    if best < 7 or best_end is None:
        return []
    if (today - best_end).days > 120:
        return []
    return [card(
        "longest_daily_streak", "pr", "👑", f"역대 최장 {best}일 연속",
        (f"지금까지 가장 길게 이어간 연속 러닝이 {best}일이에요. {best_end.isoformat()}에 마무리된 "
         f"이 기록은 꾸준함의 개인 최고치 — 다음엔 이걸 넘어볼 차례예요."),
        {"days": best, "end_date": best_end.isoformat()},
        min(0.92, 0.5 + best / 30),
        f"역대 최장 연속 러닝 {best}일({best_end.isoformat()} 종료). 기록의 의미와 안전한 갱신 전략 코칭.")]


def _weekly_km(runs: List[dict]) -> dict:
    by_week = defaultdict(float)
    for r in runs:
        if r.get("date") is None:
            continue
        by_week[r["date"].isocalendar()[:2]] += (r["dist"] or 0)
    return by_week


def target_km_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Consecutive weeks meeting the week's target_km."""
    today = ctx.get("today")
    week_meta = ctx.get("week_meta") or {}
    target = week_meta.get("target_km")
    if today is None or not target or target <= 0:
        return []
    by_week = _weekly_km(runs)
    if not by_week:
        return []
    streak = 0
    bar = target * 0.92
    for step in range(1, 60):
        wk = (today - _dt.timedelta(days=7 * step)).isocalendar()[:2]
        if by_week.get(wk, 0.0) >= bar:
            streak += 1
        else:
            break
    if streak < 3:
        return []
    return [card(
        "target_km_streak", "consistency", "🎯", f"목표 거리 {streak}주 연속 달성",
        (f"주간 목표 거리(약 {target:.0f}km)를 {streak}주 연속으로 채웠어요. 계획대로 쌓이는 거리가 "
         f"레이스 당일의 자신감으로 이어져요."),
        {"weeks": streak, "target_km": round(target, 1)},
        min(0.88, 0.42 + streak / 18),
        f"주간 목표 {target:.0f}km를 {streak}주 연속 달성. 계획 준수의 의미와 다음 단계 강도 코칭.")]


def no_rest_week_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Consecutive weeks in which at least one run was logged."""
    today = ctx.get("today")
    if today is None:
        return []
    by_week = _weekly_km(runs)
    if not by_week:
        return []
    streak = 0
    for step in range(0, 200):
        wk = (today - _dt.timedelta(days=7 * step)).isocalendar()[:2]
        ran = by_week.get(wk, 0.0) > 0
        if step == 0 and not ran:
            continue
        if ran:
            streak += 1
        else:
            break
    if streak < 6:
        return []
    months = streak / 4.345
    return [card(
        "no_rest_week_streak", "consistency", "📆", f"{streak}주 연속 빠진 주 없음",
        (f"{streak}주 동안 단 한 주도 거르지 않고 달렸어요(약 {months:.1f}개월). 한 번도 손을 놓지 않은 "
         f"이 연속성이 부상·정체 없이 성장하는 러너의 공통점이에요."),
        {"weeks": streak, "months": round(months, 1)},
        min(0.85, 0.4 + streak / 26),
        f"{streak}주 연속 빠진 주 없이 러닝 유지(약 {months:.1f}개월). 장기 지속성 칭찬과 리듬 유지 코칭.")]


def comeback_after_gap(runs: List[dict], ctx: dict) -> List[dict]:
    """Return after a meaningful layoff: a >=14-day gap that ended recently."""
    today = ctx.get("today")
    if today is None:
        return []
    dates = _run_dates(runs)
    if len(dates) < 4:
        return []
    gap_days = 0
    return_date = None
    for prev, nxt in zip(dates, dates[1:]):
        g = (nxt - prev).days
        if g >= 14 and (today - nxt).days <= 35:
            gap_days = g
            return_date = nxt
    if return_date is None or gap_days < 14:
        return []
    since = [d for d in dates if d >= return_date]
    if len(since) < 3:
        return []
    days_back = (today - return_date).days
    weeks_off = gap_days / 7.0
    return [card(
        "comeback_after_gap", "consistency", "🔄", f"{int(round(weeks_off))}주 공백 딛고 복귀",
        (f"약 {gap_days}일({weeks_off:.1f}주) 쉰 뒤 {days_back}일 전 다시 달리기 시작해, 그 사이 "
         f"{len(since)}번을 뛰었어요. 멈춤보다 다시 시작하는 힘이 진짜 실력이에요."),
        {"gap_days": gap_days, "runs_since": len(since), "return_date": return_date.isoformat(),
         "days_since_return": days_back},
        min(0.8, 0.45 + len(since) / 25),
        f"{gap_days}일 공백 후 복귀해 {len(since)}회 재개. 복귀 초기 부하 관리와 리듬 회복 코칭.")]


def weekend_long_run_habit(runs: List[dict], ctx: dict) -> List[dict]:
    """Weekend long-run habit across recent weeks."""
    today = ctx.get("today")
    if today is None:
        return []
    recent = window(runs, today, -1, 84)  # last ~12 weeks
    longs = [r for r in recent if r.get("dist") and r.get("date") is not None
             and (r.get("type") == "long" or r["dist"] >= 12)]
    if len(longs) < 4:
        return []
    weekend = [r for r in longs if r["date"].weekday() >= 5]  # Sat=5, Sun=6
    n, w = len(longs), len(weekend)
    share = w / n
    if w < 3 or share < 0.65:
        return []
    avg_km = mean([r["dist"] for r in weekend])
    if avg_km is None:
        return []
    pct = int(round(share * 100))
    return [card(
        "weekend_long_run_habit", "consistency", "🌅", f"롱런 {pct}%가 주말에",
        (f"최근 12주 롱런 {n}번 중 {w}번을 주말에 소화했어요(평균 {avg_km:.1f}km). 주말에 거리를 쌓는 "
         f"이 루틴이 한 주의 훈련을 지탱하는 기둥이에요."),
        {"long_runs": n, "weekend_runs": w, "share_pct": pct, "avg_km": round(avg_km, 1)},
        min(0.78, 0.38 + share / 2),
        f"최근 롱런 {n}회 중 {w}회가 주말(평균 {avg_km:.1f}km). 주말 롱런 루틴의 강점과 회복일 배치 코칭.")]


def perfect_week_streak(runs: List[dict], ctx: dict) -> List[dict]:
    """Consecutive weeks that each contain at least one long/quality run AND >=3 runs."""
    today = ctx.get("today")
    if today is None:
        return []
    by_week_runs = defaultdict(list)
    for r in runs:
        if r.get("date") is None or not r.get("dist"):
            continue
        by_week_runs[r["date"].isocalendar()[:2]].append(r)
    if not by_week_runs:
        return []

    def complete(wk) -> bool:
        rs = by_week_runs.get(wk, [])
        if len(rs) < 3:
            return False
        has_long = any(x.get("type") == "long" or (x.get("dist") or 0) >= 12 for x in rs)
        has_quality = any(x.get("type") in ("tempo", "interval") for x in rs)
        return has_long or has_quality

    streak = 0
    for step in range(0, 80):
        wk = (today - _dt.timedelta(days=7 * step)).isocalendar()[:2]
        ok = complete(wk)
        if step == 0 and not ok:
            continue
        if ok:
            streak += 1
        else:
            break
    if streak < 3:
        return []
    return [card(
        "perfect_week_streak", "consistency", "✅", f"알찬 주 {streak}주 연속",
        (f"주 3회 이상에 롱런이나 포인트 훈련까지 갖춘 '제대로 된 주'를 {streak}주 연속 보냈어요. "
         f"양과 질이 함께 쌓일 때 기록이 가장 빨리 좋아져요."),
        {"weeks": streak},
        min(0.84, 0.42 + streak / 16),
        f"롱런·포인트 훈련을 포함한 알찬 주 {streak}주 연속. 구조화된 주간 훈련의 효과와 유지 코칭.")]


DETECTORS = [
    daily_streak,
    longest_daily_streak,
    target_km_streak,
    no_rest_week_streak,
    comeback_after_gap,
    weekend_long_run_habit,
    perfect_week_streak,
]
