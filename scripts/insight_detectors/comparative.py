"""Comparative + narrative insight detectors.

Self-relative storytelling: month-over-month distance/pace deltas, personal-history
percentiles (where the latest run ranks), rolling "best block ever" (last 4 weeks vs all
historical 4-week windows), previous-training-block comparison, and post-gap recovery curve.

All detectors follow the shared contract in ``_util`` — defensive (never raise), sample
guards, KST ``ctx['today']`` only. Korean copy is number-forward, no markdown.
"""
from __future__ import annotations

import statistics as _st
from typing import List

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


def _km(r) -> float:
    return r["dist"] or 0.0


def monthly_distance_delta(runs: List[dict], ctx: dict) -> List[dict]:
    """이번 30일 총거리 vs 직전 30일 총거리. 의미 있는 증감(>=20%, 절대값 가드)만 카드."""
    today = ctx["today"]
    cur = [r for r in window(runs, today, -1, 30) if r["dist"]]
    prev = [r for r in window(runs, today, 30, 60) if r["dist"]]
    if len(cur) < 3 or len(prev) < 3:
        return []
    cur_km = sum(_km(r) for r in cur)
    prev_km = sum(_km(r) for r in prev)
    if prev_km < 10 or cur_km < 10:
        return []
    ratio = cur_km / prev_km
    pct = int(round((ratio - 1) * 100))
    if abs(pct) < 20:
        return []
    if pct > 0:
        kind, icon = "improvement", "📊"
        headline = f"이번 달 거리 +{pct}%"
        wow = (f"최근 30일 {cur_km:.0f}km로 직전 30일({prev_km:.0f}km)보다 {pct}% 더 달렸어요. "
               f"볼륨이 꾸준히 늘고 있다는 신호예요.")
        score = min(0.85, 0.45 + pct / 120)
    else:
        kind, icon = "consistency", "📊"
        headline = f"이번 달 거리 {pct}%"
        wow = (f"최근 30일 {cur_km:.0f}km로 직전 30일({prev_km:.0f}km)보다 {abs(pct)}% 줄었어요. "
               f"의도한 감량이면 좋은 회복 구간, 아니면 다시 리듬을 잡을 때예요.")
        score = min(0.7, 0.35 + abs(pct) / 150)
    return [card(
        "monthly_distance_delta", kind, icon, headline, wow,
        {"cur_km": round(cur_km), "prev_km": round(prev_km), "pct": pct,
         "n_cur": len(cur), "n_prev": len(prev)},
        score,
        (f"최근 30일 {cur_km:.0f}km, 직전 30일 {prev_km:.0f}km로 {pct}% 변화. "
         f"볼륨 추세 의미와 다음 한 달 운영 방향 코칭."))]


def monthly_pace_delta(runs: List[dict], ctx: dict) -> List[dict]:
    """이지런 평균 페이스의 월 대비 변화. 최근 30일 vs 직전 30일, >=6초/km 빨라졌을 때만."""
    today = ctx["today"]
    easy_types = ("easy", "recovery", "long")
    cur = [r for r in window(runs, today, -1, 30)
           if r["type"] in easy_types and r["pace_s"] and r["dist"]]
    prev = [r for r in window(runs, today, 30, 60)
            if r["type"] in easy_types and r["pace_s"] and r["dist"]]
    if len(cur) < 3 or len(prev) < 3:
        return []
    cp = _st.mean(r["pace_s"] for r in cur)
    pp = _st.mean(r["pace_s"] for r in prev)
    delta = pp - cp
    if delta < 6:
        return []
    return [card(
        "monthly_pace_delta", "improvement", "⏱️",
        f"이지 페이스 한 달 새 {int(round(delta))}초 빨라짐",
        (f"최근 30일 이지런 평균이 {fmt_pace(cp)}/km로, 직전 30일({fmt_pace(pp)}/km)보다 "
         f"{int(round(delta))}초/km 빨라졌어요. 편하게 달리는 속도 자체가 올라간 거예요."),
        {"cur_pace": fmt_pace(cp), "prev_pace": fmt_pace(pp), "delta_s": int(round(delta)),
         "n_cur": len(cur), "n_prev": len(prev)},
        min(0.85, 0.45 + delta / 60),
        (f"이지런 평균 페이스 {fmt_pace(pp)}→{fmt_pace(cp)}/km, 한 달 새 {int(round(delta))}초/km 개선. "
         f"심박 데이터가 없을 수 있으니 컨디션·코스 변수도 짚으며 의미 코칭."))]


def pace_percentile(runs: List[dict], ctx: dict) -> List[dict]:
    """자기 이력 백분위: 가장 최근 런(>=3km)의 페이스가 같은 거리대 역대 상위 몇%인지."""
    today = ctx["today"]
    scored = [r for r in runs if r["pace_s"] and r["dist"] and r["dist"] >= 3]
    if len(scored) < 15:
        return []
    latest = max(scored, key=lambda r: r["date"])
    if age(latest, today) > 10:
        return []
    lo, hi = latest["dist"] * 0.8, latest["dist"] * 1.25
    peers = [r for r in scored if lo <= r["dist"] <= hi and r is not latest]
    if len(peers) < 10:
        return []
    faster_or_equal = sum(1 for r in peers if r["pace_s"] <= latest["pace_s"])
    pct_top = int(round(100 * (faster_or_equal + 1) / (len(peers) + 1)))
    if pct_top > 15:
        return []
    return [card(
        "pace_percentile", "pr", "🎯",
        f"이 페이스 역대 상위 {pct_top}%",
        (f"최근 {latest['dist']:.1f}km를 {fmt_pace(latest['pace_s'])}/km로 달렸는데, 비슷한 거리"
         f"({lo:.0f}~{hi:.0f}km) 기록 {len(peers)}개 중 상위 {pct_top}%에 드는 빠른 런이에요."),
        {"pace": fmt_pace(latest["pace_s"]), "distance_km": round(latest["dist"], 1),
         "percentile_top": pct_top, "n_peers": len(peers), "date": latest["date"].isoformat()},
        min(0.9, 0.5 + (16 - pct_top) / 40),
        (f"최근 {latest['dist']:.1f}km {fmt_pace(latest['pace_s'])}/km는 같은 거리대 역대 상위 {pct_top}%. "
         f"무엇이 좋았는지, 이 감각을 어떻게 재현할지 코칭."))]


def best_rolling_block(runs: List[dict], ctx: dict) -> List[dict]:
    """롤링 인생 최고 구간: 최근 4주 이지런 평균 페이스가 역대 모든 4주 윈도우 중 최고일 때."""
    today = ctx["today"]
    easy_types = ("easy", "recovery", "long")
    pool = [r for r in runs if r["type"] in easy_types and r["pace_s"] and r["dist"]
            and r["dist"] >= 3]
    if len(pool) < 16:
        return []
    recent = [r for r in pool if age(r, today) <= 28]
    if len(recent) < 4:
        return []
    recent_avg = _st.mean(r["pace_s"] for r in recent)
    # 직전 4주 단위 과거 윈도우들 (오프셋 28, 56, ... 일)
    best_past = None
    for off in range(28, 28 * 9, 28):
        win = [r for r in pool if off < age(r, today) <= off + 28]
        if len(win) >= 4:
            avg = _st.mean(r["pace_s"] for r in win)
            if best_past is None or avg < best_past:
                best_past = avg
    if best_past is None:
        return []
    gain = best_past - recent_avg
    if gain < 4:
        return []
    return [card(
        "best_rolling_block", "pr", "🏆",
        f"최근 4주가 역대 최고 이지 페이스",
        (f"최근 4주 이지런 평균이 {fmt_pace(recent_avg)}/km로, 역대 어느 4주 구간보다 빨라요. "
         f"종전 최고 구간({fmt_pace(best_past)}/km)보다 {int(round(gain))}초/km 앞섰어요."),
        {"recent_avg_pace": fmt_pace(recent_avg), "best_past_pace": fmt_pace(best_past),
         "gain_s": int(round(gain)), "n_recent": len(recent)},
        min(0.95, 0.6 + gain / 40),
        (f"최근 4주 이지 평균 {fmt_pace(recent_avg)}/km가 역대 4주 최고(종전 {fmt_pace(best_past)}/km, "
         f"{int(round(gain))}초/km 개선). 인생 최고 폼이라는 점과 유지·전환 코칭."))]


def block_vs_block(runs: List[dict], ctx: dict) -> List[dict]:
    """직전 블록 대비: 최근 4주 vs 그 직전 4주의 빈도+거리 종합 변화."""
    today = ctx["today"]
    cur = [r for r in runs if age(r, today) <= 28 and r["dist"]]
    prev = [r for r in runs if 28 < age(r, today) <= 56 and r["dist"]]
    if len(cur) < 4 or len(prev) < 4:
        return []
    cur_km, prev_km = sum(_km(r) for r in cur), sum(_km(r) for r in prev)
    cur_n, prev_n = len(cur), len(prev)
    if prev_km < 10:
        return []
    km_pct = int(round((cur_km / prev_km - 1) * 100))
    n_diff = cur_n - prev_n
    # 빈도가 늘고 거리도 의미 있게 늘어난 "블록 업그레이드"만 카드.
    if not (n_diff >= 1 and km_pct >= 15):
        return []
    return [card(
        "block_vs_block", "improvement", "🧱",
        f"직전 블록보다 {cur_n}회·{km_pct:+d}%",
        (f"최근 4주 {cur_n}회 {cur_km:.0f}km로, 직전 4주({prev_n}회 {prev_km:.0f}km)보다 "
         f"{n_diff}회 더 뛰고 거리도 {km_pct}% 늘었어요. 훈련 블록이 한 단계 두꺼워졌어요."),
        {"cur_runs": cur_n, "prev_runs": prev_n, "cur_km": round(cur_km),
         "prev_km": round(prev_km), "km_pct": km_pct},
        min(0.85, 0.45 + km_pct / 120 + n_diff / 20),
        (f"최근 4주 {cur_n}회 {cur_km:.0f}km vs 직전 4주 {prev_n}회 {prev_km:.0f}km. "
         f"빈도·볼륨 동시 상승의 의미와 과부하 없이 이어갈 운영 코칭."))]


def comeback_curve(runs: List[dict], ctx: dict) -> List[dict]:
    """공백 후 회복 곡선: 14일+ 휴식 뒤 복귀해, 복귀 첫 런 대비 최근 런 페이스가 회복된 정도."""
    today = ctx["today"]
    seq = sorted([r for r in runs if r["dist"] and r["dist"] >= 2 and r["pace_s"]],
                 key=lambda r: r["date"])
    if len(seq) < 6:
        return []
    # 가장 최근의 14일+ 공백 찾기 (그 공백 직후가 복귀 시작점).
    gap_idx = None
    for i in range(1, len(seq)):
        if (seq[i]["date"] - seq[i - 1]["date"]).days >= 14:
            gap_idx = i
    if gap_idx is None:
        return []
    comeback = seq[gap_idx:]
    if len(comeback) < 4:
        return []
    if age(comeback[-1], today) > 14:
        return []
    gap_days = (comeback[0]["date"] - seq[gap_idx - 1]["date"]).days
    first_pace = comeback[0]["pace_s"]
    recent = comeback[-3:]
    recent_pace = _st.mean(r["pace_s"] for r in recent)
    recovered = first_pace - recent_pace
    if recovered < 8:
        return []
    n_back = len(comeback)
    return [card(
        "comeback_curve", "adaptation", "🔁",
        f"공백 복귀 후 {int(round(recovered))}초 회복",
        (f"{gap_days}일 쉰 뒤 복귀 첫 런은 {fmt_pace(first_pace)}/km였는데, 최근엔 "
         f"{fmt_pace(recent_pace)}/km예요. {n_back}번 만에 {int(round(recovered))}초/km를 되찾았어요."),
        {"gap_days": gap_days, "first_pace": fmt_pace(first_pace),
         "recent_pace": fmt_pace(recent_pace), "recovered_s": int(round(recovered)),
         "n_runs_back": n_back},
        min(0.85, 0.45 + recovered / 60),
        (f"{gap_days}일 공백 복귀 후 {n_back}번 만에 페이스 {fmt_pace(first_pace)}→{fmt_pace(recent_pace)}/km "
         f"({int(round(recovered))}초/km 회복). 복귀 곡선이 건강하다는 점과 무리 없는 가속 코칭."))]


def longest_run_streak_pr(runs: List[dict], ctx: dict) -> List[dict]:
    """자기 이력 거리 백분위: 최근 롱런이 역대 거리 분포 상위에 들 때(상위 10% 이내)."""
    today = ctx["today"]
    dists = [r for r in runs if r["dist"] and r["dist"] >= 5]
    if len(dists) < 15:
        return []
    latest_long = max((r for r in dists if age(r, today) <= 14),
                      key=lambda r: r["dist"], default=None)
    if latest_long is None:
        return []
    peers = [r["dist"] for r in dists if r is not latest_long]
    if len(peers) < 12:
        return []
    below = sum(1 for d in peers if d < latest_long["dist"])
    pct_top = int(round(100 * (1 - below / len(peers))))
    if pct_top > 10:
        return []
    med = median(peers) or 0
    return [card(
        "distance_percentile", "pr", "📏",
        f"최근 롱런 역대 거리 상위 {pct_top}%",
        (f"최근 {latest_long['dist']:.1f}km는 역대 런 {len(peers)}개 중 상위 {pct_top}%에 드는 긴 거리예요. "
         f"평소 중앙값({med:.1f}km)보다 확실히 길게 달렸어요."),
        {"distance_km": round(latest_long["dist"], 1), "percentile_top": pct_top,
         "median_km": round(med, 1), "n_peers": len(peers),
         "date": latest_long["date"].isoformat()},
        min(0.85, 0.45 + (11 - pct_top) / 30),
        (f"최근 {latest_long['dist']:.1f}km가 역대 거리 상위 {pct_top}%(중앙값 {med:.1f}km). "
         f"지구력 확장의 의미와 회복·다음 롱런 간격 코칭."))]


DETECTORS = [
    monthly_distance_delta,
    monthly_pace_delta,
    pace_percentile,
    best_rolling_block,
    block_vs_block,
    comeback_curve,
    longest_run_streak_pr,
]
