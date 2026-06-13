"""Records & milestones detectors (category: records_milestones).

Self-relative records and milestones built almost entirely from distance / pace /
duration (≈99% coverage), so these stay robust even without HR or cadence. Each
detector only surfaces a card when it clears a meaningful threshold, defends
against None, guards a minimum sample, and never raises.

See ``_util`` for the detector/card contract and ``core`` for style. IDs here do
NOT reuse any core id (aerobic_efficiency, pr_longest, pr_fast_long, pr_cadence,
load_spike, consistency_weeks, cadence_trend, hill_adaptation).
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter
from typing import List

from insight_detectors._util import card, fmt_pace


# --------------------------------------------------------------------------- #
# helpers (module-local; keep them tiny and None-safe)
# --------------------------------------------------------------------------- #
def _dist(r) -> float:
    d = r.get("dist")
    return d if isinstance(d, (int, float)) and d > 0 else 0.0


def _month_key(d: _dt.date):
    return (d.year, d.month)


def _month_label(key) -> str:
    return f"{key[0]}년 {key[1]}월"


# --------------------------------------------------------------------------- #
# 1. Cumulative distance milestone (1000 / 2000 / ... km crossed)
# --------------------------------------------------------------------------- #
def cumulative_distance_milestone(runs: List[dict], ctx: dict) -> List[dict]:
    """누적 거리가 1000km 배수 마일스톤을 최근에 돌파했는지."""
    try:
        today = ctx["today"]
        ordered = sorted((r for r in runs if _dist(r) > 0), key=lambda r: r["date"])
        if len(ordered) < 5:
            return []
        total = 0.0
        crossed = None  # (milestone_km, run)
        for r in ordered:
            before = total
            total += _dist(r)
            step = int(before // 1000)
            new_step = int(total // 1000)
            if new_step > step and new_step >= 1:
                crossed = (new_step * 1000, r)  # keep the latest crossing
        if not crossed:
            return []
        milestone_km, run = crossed
        days_since = (today - run["date"]).days
        if days_since > 45:  # only celebrate fresh crossings
            return []
        return [card(
            "cumulative_distance_milestone", "pr", "🎖️",
            f"누적 {milestone_km:,}km 돌파",
            (f"기록을 시작한 뒤 함께 달린 거리가 {milestone_km:,}km를 넘었어요. "
             f"지금까지 총 {total:.0f}km — 한 걸음씩 쌓아온 결과예요."),
            {"milestone_km": milestone_km, "total_km": round(total),
             "date": run["date"].isoformat(), "days_since": days_since},
            min(0.95, 0.6 + milestone_km / 10000),
            (f"누적 거리 {milestone_km:,}km 돌파(현재 총 {total:.0f}km, {days_since}일 전). "
             f"여정의 의미를 짚어주고 다음 마일스톤까지 동기 부여 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 2. Cumulative run-count milestone (50 / 100 / 200 / ... runs)
# --------------------------------------------------------------------------- #
def run_count_milestone(runs: List[dict], ctx: dict) -> List[dict]:
    """기록된 누적 런 횟수가 50/100/200/300/500/750/1000회 마일스톤을 최근에 도달했는지."""
    try:
        today = ctx["today"]
        ordered = sorted((r for r in runs if _dist(r) > 0), key=lambda r: r["date"])
        n = len(ordered)
        if n < 10:
            return []
        marks = [50, 100, 200, 300, 400, 500, 750, 1000, 1500, 2000]
        # the run index (1-based) reaches a mark exactly at that run
        if n not in marks:
            return []
        run = ordered[n - 1]
        if (today - run["date"]).days > 45:
            return []
        return [card(
            "run_count_milestone", "pr", "🏃",
            f"{n}번째 러닝 달성",
            (f"기록상 {n}번째 러닝을 마쳤어요. 횟수가 쌓인다는 건 러닝이 일상이 됐다는 가장 "
             f"솔직한 증거예요."),
            {"count": n, "date": run["date"].isoformat()},
            min(0.9, 0.5 + n / 2000),
            (f"누적 {n}회 러닝 마일스톤 도달. 꾸준함을 인정하고 다음 라운드 넘버까지 "
             f"이어갈 동기 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 3. Biggest distance month ever (a new monthly volume record)
# --------------------------------------------------------------------------- #
def biggest_month_distance(runs: List[dict], ctx: dict) -> List[dict]:
    """이번 달(또는 직전 달) 누적 거리가 역대 월 최다 거리인지."""
    try:
        today = ctx["today"]
        by_month: Counter = Counter()
        for r in runs:
            d = _dist(r)
            if d > 0:
                by_month[_month_key(r["date"])] += d
        if len(by_month) < 3:
            return []
        cur_key = _month_key(today)
        prev_key = _month_key(today.replace(day=1) - _dt.timedelta(days=1))
        # candidate = the most recent month with data among current/previous
        cand_key = cur_key if by_month.get(cur_key) else prev_key
        cand_km = by_month.get(cand_key, 0.0)
        if cand_km <= 0:
            return []
        others = [(k, v) for k, v in by_month.items() if k != cand_key]
        if not others:
            return []
        prev_best_key, prev_best = max(others, key=lambda kv: kv[1])
        if cand_km <= prev_best or cand_km - prev_best < 3:  # need a real margin
            return []
        # if it's the still-running current month, require it already cleared the record
        gain = cand_km - prev_best
        return [card(
            "biggest_month_distance", "pr", "📅",
            f"{_month_label(cand_key)} {cand_km:.0f}km, 역대 월 최다",
            (f"{_month_label(cand_key)}에 {cand_km:.0f}km를 달렸어요. 지금까지 가장 많이 달린 달이던 "
             f"{_month_label(prev_best_key)}({prev_best:.0f}km)을 {gain:.0f}km 넘어선 새 기록이에요."),
            {"month": f"{cand_key[0]}-{cand_key[1]:02d}", "distance_km": round(cand_km),
             "prev_best_km": round(prev_best),
             "prev_best_month": f"{prev_best_key[0]}-{prev_best_key[1]:02d}",
             "gain_km": round(gain)},
            min(0.9, 0.5 + gain / 80),
            (f"월 최다 거리 경신({_month_label(cand_key)} {cand_km:.0f}km, 이전 최고 {prev_best:.0f}km). "
             f"볼륨 증가의 의미와 회복 균형 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 4. Year-to-date vs same window last year
# --------------------------------------------------------------------------- #
def ytd_vs_last_year(runs: List[dict], ctx: dict) -> List[dict]:
    """올해 1/1~오늘 누적 거리 vs 작년 같은 기간(1/1~같은 월·일) 비교."""
    try:
        today = ctx["today"]
        y = today.year
        ytd = sum(_dist(r) for r in runs
                  if r["date"].year == y and r["date"] <= today)
        # same-window last year: jan1..(month,day) of last year
        try:
            last_cut = today.replace(year=y - 1)
        except ValueError:  # Feb 29 -> Feb 28
            last_cut = today.replace(year=y - 1, day=28)
        last = sum(_dist(r) for r in runs
                   if r["date"].year == y - 1 and r["date"] <= last_cut)
        if ytd < 30 or last < 30:  # need a meaningful base both years
            return []
        diff = ytd - last
        pct = diff / last * 100
        if abs(pct) < 12:  # only when clearly ahead/behind
            return []
        if diff > 0:
            return [card(
                "ytd_vs_last_year", "improvement", "📈",
                f"올해 누적 {ytd:.0f}km, 작년 대비 +{pct:.0f}%",
                (f"올해 들어 지금까지 {ytd:.0f}km를 달렸어요. 작년 같은 기간({last:.0f}km)보다 "
                 f"{diff:.0f}km({pct:.0f}%) 더 많아요 — 작년의 나를 이미 앞서고 있어요."),
                {"ytd_km": round(ytd), "last_year_km": round(last),
                 "diff_km": round(diff), "pct": round(pct)},
                min(0.85, 0.45 + pct / 200),
                (f"올해 누적 {ytd:.0f}km로 작년 동기간 {last:.0f}km 대비 {pct:.0f}% 앞섬. "
                 f"성장 추세를 강화하되 무리하지 않게 페이싱 코칭."))]
        # behind last year: gentle nudge (kind=consistency, lower score)
        return [card(
            "ytd_vs_last_year", "consistency", "🗓️",
            f"올해 누적 {ytd:.0f}km, 작년보다 {-pct:.0f}% 적어요",
            (f"올해 누적은 {ytd:.0f}km로 작년 같은 기간({last:.0f}km)보다 {-diff:.0f}km 적어요. "
             f"숫자에 쫓길 필요는 없지만, 주 1회만 더 채워도 금세 따라잡을 수 있어요."),
            {"ytd_km": round(ytd), "last_year_km": round(last),
             "diff_km": round(diff), "pct": round(pct)},
            min(0.6, 0.3 + (-pct) / 200),
            (f"올해 누적 {ytd:.0f}km로 작년 동기간 {last:.0f}km보다 {-pct:.0f}% 적음. "
             f"부담 주지 않으면서 리듬 회복 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 5. Longest-duration run ever (time on feet, not distance)
# --------------------------------------------------------------------------- #
def longest_duration_run(runs: List[dict], ctx: dict) -> List[dict]:
    """역대 가장 오래 달린 런(시간 기준). 최근 30일 내 신기록일 때만."""
    try:
        today = ctx["today"]
        durs = [r for r in runs if isinstance(r.get("dur"), (int, float)) and r["dur"] > 0]
        if len(durs) < 8:
            return []
        best = max(durs, key=lambda r: r["dur"])
        if (today - best["date"]).days > 30:
            return []
        prior = [r for r in durs if r["date"] < best["date"]]
        if len(prior) < 5:
            return []
        prev_best = max(prior, key=lambda r: r["dur"])
        if best["dur"] <= prev_best["dur"]:
            return []
        gain_min = (best["dur"] - prev_best["dur"]) / 60.0
        if gain_min < 3:  # ignore trivial improvements
            return []
        h, m = divmod(int(round(best["dur"] / 60)), 60)
        cur_label = f"{h}시간 {m}분" if h else f"{m}분"
        ph, pm = divmod(int(round(prev_best["dur"] / 60)), 60)
        prev_label = f"{ph}시간 {pm}분" if ph else f"{pm}분"
        dist_part = f", {best['dist']:.1f}km" if _dist(best) > 0 else ""
        return [card(
            "longest_duration_run", "pr", "⏱️",
            f"역대 최장 시간 {cur_label} 러닝",
            (f"한 번에 {cur_label} 동안 달렸어요{dist_part}. 이전 최장({prev_label})을 넘어선 "
             f"역대 가장 오래 달린 런이에요 — 버티는 힘이 확실히 늘었어요."),
            {"duration_s": int(best["dur"]), "prev_s": int(prev_best["dur"]),
             "gain_min": round(gain_min), "date": best["date"].isoformat(),
             "distance_km": round(_dist(best), 1) if _dist(best) > 0 else None},
            min(0.9, 0.5 + gain_min / 40),
            (f"역대 최장 시간 런 경신({cur_label}, 이전 {prev_label}). "
             f"시간 기반 지구력의 의미와 회복 운영 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 6. Fastest equivalent 5k (best sustained pace over a 5k+ run)
# --------------------------------------------------------------------------- #
def fastest_5k_equiv(runs: List[dict], ctx: dict) -> List[dict]:
    """5km 이상 런 중 가장 빠른 페이스 → 5k 환산 최속. 최근 21일 내 신기록일 때만."""
    try:
        today = ctx["today"]
        c = [r for r in runs
             if _dist(r) >= 5.0 and isinstance(r.get("pace_s"), (int, float)) and r["pace_s"] > 0]
        if len(c) < 6:
            return []
        best = min(c, key=lambda r: r["pace_s"])
        if (today - best["date"]).days > 21:
            return []
        prior = [r for r in c if r["date"] < best["date"]]
        if len(prior) < 4:
            return []
        prev_best = min(prior, key=lambda r: r["pace_s"])
        if best["pace_s"] >= prev_best["pace_s"]:
            return []
        gain = prev_best["pace_s"] - best["pace_s"]
        if gain < 3:
            return []
        eq_5k_s = int(round(best["pace_s"] * 5))
        eh, em = divmod(eq_5k_s, 60)
        eq_label = f"{eh}:{em:02d}" if eh else f"{em}초"
        return [card(
            "fastest_5k_equiv", "pr", "⚡",
            f"5km 환산 최속 {fmt_pace(best['pace_s'])}/km",
            (f"{best['dist']:.1f}km를 {fmt_pace(best['pace_s'])}/km로 달렸어요. 5km 환산 약 "
             f"{eh}분 {em}초 수준 — 5km 이상 거리에서 역대 가장 빠른 페이스예요"
             f"(이전 {fmt_pace(prev_best['pace_s'])}/km)."),
            {"pace": fmt_pace(best["pace_s"]), "prev_pace": fmt_pace(prev_best["pace_s"]),
             "distance_km": round(best["dist"], 1), "eq_5k": eq_label,
             "gain_s": int(gain), "date": best["date"].isoformat()},
            min(0.9, 0.5 + gain / 40),
            (f"5km 환산 최속 경신({fmt_pace(best['pace_s'])}/km, 이전 {fmt_pace(prev_best['pace_s'])}/km). "
             f"스피드 향상의 의미와 다음 자극 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 7. Fastest equivalent 10k (best sustained pace over a 10k+ run)
# --------------------------------------------------------------------------- #
def fastest_10k_equiv(runs: List[dict], ctx: dict) -> List[dict]:
    """10km 이상 런 중 가장 빠른 페이스 → 10k 환산 최속. 최근 28일 내 신기록일 때만."""
    try:
        today = ctx["today"]
        c = [r for r in runs
             if _dist(r) >= 10.0 and isinstance(r.get("pace_s"), (int, float)) and r["pace_s"] > 0]
        if len(c) < 5:
            return []
        best = min(c, key=lambda r: r["pace_s"])
        if (today - best["date"]).days > 28:
            return []
        prior = [r for r in c if r["date"] < best["date"]]
        if len(prior) < 3:
            return []
        prev_best = min(prior, key=lambda r: r["pace_s"])
        if best["pace_s"] >= prev_best["pace_s"]:
            return []
        gain = prev_best["pace_s"] - best["pace_s"]
        if gain < 3:
            return []
        eq_10k_s = int(round(best["pace_s"] * 10))
        eh, em = divmod(eq_10k_s, 60)
        return [card(
            "fastest_10k_equiv", "pr", "🚀",
            f"10km 환산 최속 {fmt_pace(best['pace_s'])}/km",
            (f"{best['dist']:.1f}km를 평균 {fmt_pace(best['pace_s'])}/km로 — 10km 환산 약 "
             f"{eh}분 {em}초예요. 10km 이상 거리에서 역대 가장 빠른 페이스로"
             f"(이전 {fmt_pace(prev_best['pace_s'])}/km) 지구력과 스피드가 함께 올라온 신호예요."),
            {"pace": fmt_pace(best["pace_s"]), "prev_pace": fmt_pace(prev_best["pace_s"]),
             "distance_km": round(best["dist"], 1), "eq_10k": f"{eh}:{em:02d}",
             "gain_s": int(gain), "date": best["date"].isoformat()},
            min(0.92, 0.52 + gain / 40),
            (f"10km 환산 최속 경신({fmt_pace(best['pace_s'])}/km, 이전 {fmt_pace(prev_best['pace_s'])}/km). "
             f"긴 거리 스피드 향상의 의미와 활용 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 8. Biggest single-week distance ever (calendar ISO-week volume record)
# --------------------------------------------------------------------------- #
def biggest_week_distance(runs: List[dict], ctx: dict) -> List[dict]:
    """ISO 주 단위 누적 거리가 역대 주 최다인지(core의 PR/부하 지표와 다른 주간 볼륨 기록)."""
    try:
        today = ctx["today"]
        by_week: Counter = Counter()
        for r in runs:
            d = _dist(r)
            if d > 0:
                by_week[r["date"].isocalendar()[:2]] += d
        if len(by_week) < 4:
            return []
        cur_wk = today.isocalendar()[:2]
        cur_km = by_week.get(cur_wk, 0.0)
        if cur_km <= 0:
            return []
        others = [(k, v) for k, v in by_week.items() if k != cur_wk]
        if not others:
            return []
        prev_best_wk, prev_best = max(others, key=lambda kv: kv[1])
        if cur_km <= prev_best or cur_km - prev_best < 2:
            return []
        gain = cur_km - prev_best
        return [card(
            "biggest_week_distance", "pr", "📊",
            f"이번 주 {cur_km:.0f}km, 역대 주간 최다",
            (f"이번 주에 {cur_km:.0f}km를 달렸어요. 지금까지 가장 많이 달린 한 주"
             f"({prev_best:.0f}km)를 {gain:.0f}km 넘어선 새 주간 기록이에요. "
             f"다음 주는 한 단계 낮춰 회복을 챙기면 이 볼륨이 체력으로 굳어져요."),
            {"week_km": round(cur_km), "prev_best_km": round(prev_best),
             "gain_km": round(gain),
             "prev_best_week": f"{prev_best_wk[0]}-W{prev_best_wk[1]:02d}"},
            min(0.88, 0.48 + gain / 50),
            (f"주간 최다 거리 경신(이번 주 {cur_km:.0f}km, 이전 최고 {prev_best:.0f}km). "
             f"볼륨 점프 이후 회복 주차 운영 코칭."))]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# 9. Most active month by run count (frequency record)
# --------------------------------------------------------------------------- #
def most_runs_in_month(runs: List[dict], ctx: dict) -> List[dict]:
    """한 달 동안의 러닝 횟수가 역대 최다인지(빈도 기반 마일스톤)."""
    try:
        today = ctx["today"]
        cnt: Counter = Counter()
        for r in runs:
            if _dist(r) > 0:
                cnt[_month_key(r["date"])] += 1
        if len(cnt) < 3:
            return []
        cur_key = _month_key(today)
        prev_key = _month_key(today.replace(day=1) - _dt.timedelta(days=1))
        cand_key = cur_key if cnt.get(cur_key) else prev_key
        cand_n = cnt.get(cand_key, 0)
        if cand_n < 8:  # a frequency record only matters above a real floor
            return []
        others = [(k, v) for k, v in cnt.items() if k != cand_key]
        if not others:
            return []
        prev_best_key, prev_best = max(others, key=lambda kv: kv[1])
        if cand_n <= prev_best:
            return []
        return [card(
            "most_runs_in_month", "consistency", "🗓️",
            f"{_month_label(cand_key)} {cand_n}회 러닝, 역대 최다",
            (f"{_month_label(cand_key)}에 {cand_n}번 달렸어요. 한 달 기준 가장 자주 달린 기록"
             f"(이전 {prev_best}회)이에요 — 거리보다 자주 신는 신발이 결국 실력을 만들어요."),
            {"month": f"{cand_key[0]}-{cand_key[1]:02d}", "count": cand_n,
             "prev_best": prev_best,
             "prev_best_month": f"{prev_best_key[0]}-{prev_best_key[1]:02d}"},
            min(0.82, 0.42 + cand_n / 60),
            (f"월 최다 러닝 횟수 경신({_month_label(cand_key)} {cand_n}회, 이전 {prev_best}회). "
             f"빈도 기반 꾸준함 칭찬 + 강도 균형 코칭."))]
    except Exception:
        return []


DETECTORS = [
    cumulative_distance_milestone,
    run_count_milestone,
    biggest_month_distance,
    ytd_vs_last_year,
    longest_duration_run,
    fastest_5k_equiv,
    fastest_10k_equiv,
    biggest_week_distance,
    most_runs_in_month,
]
