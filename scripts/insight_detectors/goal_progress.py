"""Goal-progress insight detectors — how close the runner is to the goal-race target.

Focus: closing the target_pace gap (recent tempo/interval pace vs goal target_pace),
predicted race time from current_pb, long-run readiness vs weeks_remaining, longest-run
ratio against goal distance, projected-finish trend. If goal/profile are empty, return [].

Follows the detector/card contract in ``_util``.
"""
from __future__ import annotations

import statistics as _st
from typing import List, Optional

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


# ---------------------------------------------------------------------------
# small local helpers (defensive parsing of goal/profile strings)
# ---------------------------------------------------------------------------

def _parse_clock(s) -> Optional[int]:
    """'H:MM:SS' / 'MM:SS' / 'M:SS' → total seconds. None on anything weird."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s) if s > 0 else None
    if not isinstance(s, str):
        return None
    # tolerate a unit suffix on paces ('4:30/km' → '4:30')
    parts = s.strip().split("/")[0].strip().split(":")
    if not parts or any(not p.strip().lstrip("-").isdigit() for p in parts):
        return None
    try:
        nums = [int(p) for p in parts]
    except (ValueError, TypeError):
        return None
    if len(nums) == 3:
        total = nums[0] * 3600 + nums[1] * 60 + nums[2]
    elif len(nums) == 2:
        total = nums[0] * 60 + nums[1]
    elif len(nums) == 1:
        total = nums[0]
    else:
        return None
    return total if total > 0 else None


# canonical goal-event distances in km
_EVENT_KM = {
    "5k": 5.0, "5km": 5.0,
    "10k": 10.0, "10km": 10.0,
    "half": 21.0975, "half_marathon": 21.0975, "halfmarathon": 21.0975, "21k": 21.0975,
    "full": 42.195, "marathon": 42.195, "full_marathon": 42.195, "42k": 42.195,
}

# Riegel exponent for race-time prediction across distances.
_RIEGEL = 1.06


def _event_key(goal) -> Optional[str]:
    if not goal:
        return None
    ev = goal.get("event")
    if not ev or not isinstance(ev, str):
        return None
    return ev.strip().lower().replace(" ", "_")


def _event_km(goal) -> Optional[float]:
    return _EVENT_KM.get(_event_key(goal))


def _weeks_remaining(ctx) -> Optional[float]:
    goal = ctx.get("goal") or {}
    wr = goal.get("weeks_remaining")
    if isinstance(wr, (int, float)) and wr >= 0:
        return float(wr)
    # fall back to race_date if present
    rd = goal.get("race_date")
    today = ctx.get("today")
    if rd and today:
        try:
            import datetime as _dt
            if isinstance(rd, str):
                rd = _dt.date.fromisoformat(rd[:10])
            days = (rd - today).days
            if days >= 0:
                return days / 7.0
        except (ValueError, TypeError):
            return None
    return None


def _best_pb_seconds(profile, goal) -> Optional[tuple]:
    """Pick the most relevant current_pb entry → (event_km, total_seconds)."""
    pb = (profile or {}).get("current_pb") or {}
    if not isinstance(pb, dict):
        return None
    # prefer the goal event itself, else the closest available distance
    best = None
    cands = []
    for k, v in pb.items():
        km = _EVENT_KM.get(str(k).strip().lower())
        sec = _parse_clock(v)
        if km and sec:
            cands.append((km, sec))
    if not cands:
        return None
    goal_km = _event_km(goal)
    if goal_km:
        cands.sort(key=lambda c: abs(c[0] - goal_km))
    best = cands[0]
    return best


def _riegel_predict(km_from, sec_from, km_to) -> Optional[int]:
    if not km_from or not sec_from or not km_to or km_from <= 0 or km_to <= 0:
        return None
    return int(round(sec_from * (km_to / km_from) ** _RIEGEL))


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------

def target_pace_gap(runs: List[dict], ctx: dict) -> List[dict]:
    """How close recent quality-session pace is to the goal target_pace. Surfaces when the
    runner is within ~25s/km of target (encouraging) — uses tempo/interval runs only."""
    goal = ctx.get("goal") or {}
    tp = _parse_clock(goal.get("target_pace"))
    if not tp:
        return []
    today = ctx["today"]
    quality = [r for r in window(runs, today, -1, 42)
               if r.get("type") in ("tempo", "interval") and r.get("pace_s") and r.get("dist")]
    if len(quality) < 2:
        return []
    best = min(r["pace_s"] for r in quality)
    avg = _st.mean(r["pace_s"] for r in quality)
    gap = best - tp  # >0 means slower than target
    # only meaningful when within striking distance but not yet there
    if gap < -5 or gap > 25:
        return []
    pct = max(0.0, min(1.0, (25 - gap) / 30))
    return [card(
        "target_pace_gap", "improvement", "🎯",
        f"목표 페이스까지 {int(round(max(gap, 0)))}초",
        (f"최근 6주 템포·인터벌 최고 페이스가 {fmt_pace(best)}/km로, 목표 페이스 {fmt_pace(tp)}/km까지 "
         f"{int(round(max(gap, 0)))}초/km 남았어요. 레이스 페이스가 손에 잡히는 거리예요."),
        {"best_pace": fmt_pace(best), "target_pace": fmt_pace(tp), "avg_pace": fmt_pace(round(avg)),
         "gap_s": int(round(gap)), "n_quality": len(quality)},
        0.55 + 0.3 * pct,
        (f"최근 6주 질주 최고 {fmt_pace(best)}/km, 목표 {fmt_pace(tp)}/km까지 {int(round(max(gap, 0)))}초/km. "
         f"목표 페이스 정착을 위한 다음 자극·반복량 코칭."))]


def target_pace_gap_closing(runs: List[dict], ctx: dict) -> List[dict]:
    """The target_pace gap is shrinking: compare best quality pace in the last 3 weeks vs
    4–10 weeks ago. Rewards a closing trend even if the gap isn't zero yet."""
    goal = ctx.get("goal") or {}
    tp = _parse_clock(goal.get("target_pace"))
    if not tp:
        return []
    today = ctx["today"]

    def best_q(lo, hi):
        q = [r for r in window(runs, today, lo, hi)
             if r.get("type") in ("tempo", "interval") and r.get("pace_s")]
        return min((r["pace_s"] for r in q), default=None), len(q)

    recent, nr = best_q(-1, 21)
    base, nb = best_q(28, 70)
    if recent is None or base is None or nr < 1 or nb < 1:
        return []
    gap_now = recent - tp
    gap_then = base - tp
    closed = gap_then - gap_now  # positive = gap shrank
    if closed < 8:
        return []
    return [card(
        "target_pace_gap_closing", "improvement", "📉",
        f"목표 페이스 격차 {int(round(closed))}초 축소",
        (f"한 달여 전엔 목표 페이스({fmt_pace(tp)}/km)까지 {int(round(max(gap_then, 0)))}초 부족했는데, "
         f"최근 질주는 {int(round(max(gap_now, 0)))}초까지 좁혔어요. 격차가 빠르게 줄고 있어요."),
        {"target_pace": fmt_pace(tp), "gap_then_s": int(round(gap_then)),
         "gap_now_s": int(round(gap_now)), "closed_s": int(round(closed)),
         "best_now": fmt_pace(recent), "best_then": fmt_pace(base)},
        min(0.9, 0.5 + closed / 60),
        (f"목표 페이스 격차 {int(round(gap_then))}→{int(round(gap_now))}초로 {int(round(closed))}초 축소. "
         f"개선 동력 칭찬 + 남은 격차 메우는 훈련 코칭."))]


def predicted_race_time(runs: List[dict], ctx: dict) -> List[dict]:
    """Predicted goal-race finish from current_pb (Riegel) vs the target_time. Surfaces when
    the prediction is at or under target (on track / ahead)."""
    goal = ctx.get("goal") or {}
    profile = ctx.get("profile") or {}
    if not goal or not profile:
        return []
    goal_km = _event_km(goal)
    target = _parse_clock(goal.get("target_time"))
    if not goal_km or not target:
        return []
    src = _best_pb_seconds(profile, goal)
    if not src:
        return []
    km_from, sec_from = src
    pred = _riegel_predict(km_from, sec_from, goal_km)
    if not pred:
        return []
    margin = target - pred  # >0 means predicted faster than target
    if margin < 30:  # only celebrate when comfortably on/ahead of target
        return []
    return [card(
        "predicted_race_time", "improvement", "🔮",
        f"예상 기록 {_hms(pred)} (목표보다 {int(round(margin))}초 빠름)",
        (f"현재 PB({_pb_label(km_from)} {_hms(sec_from)}) 기준 예상 완주 기록은 {_hms(pred)}로, "
         f"목표 {_hms(target)}보다 {int(round(margin))}초 빨라요. 지금 기량이면 목표권 안이에요."),
        {"predicted": _hms(pred), "target": _hms(target), "margin_s": int(round(margin)),
         "pb_event": _pb_label(km_from), "pb_time": _hms(sec_from), "goal_km": round(goal_km, 1)},
        min(0.92, 0.5 + margin / 600),
        (f"PB 기반 예상 {_hms(pred)} vs 목표 {_hms(target)}, {int(round(margin))}초 여유. "
         f"목표 상향 또는 안정적 완주 전략 코칭."))]


def predicted_race_gap(runs: List[dict], ctx: dict) -> List[dict]:
    """Predicted finish is BEHIND target — a realistic gap to close. Warning-toned, surfaces
    when the predicted time is meaningfully over target so the plan can adjust."""
    goal = ctx.get("goal") or {}
    profile = ctx.get("profile") or {}
    if not goal or not profile:
        return []
    goal_km = _event_km(goal)
    target = _parse_clock(goal.get("target_time"))
    if not goal_km or not target:
        return []
    src = _best_pb_seconds(profile, goal)
    if not src:
        return []
    km_from, sec_from = src
    pred = _riegel_predict(km_from, sec_from, goal_km)
    if not pred:
        return []
    behind = pred - target  # >0 means slower than target
    # only when behind by a noticeable but not absurd margin
    if behind < 45 or behind > target * 0.25:
        return []
    pace_gap = behind / goal_km  # rough sec/km to find
    return [card(
        "predicted_race_gap", "warning", "🧭",
        f"목표까지 {int(round(behind))}초 더 (약 {int(round(pace_gap))}초/km)",
        (f"현재 PB 기준 예상 기록은 {_hms(pred)}로 목표 {_hms(target)}보다 {int(round(behind))}초 느려요. "
         f"레이스 페이스를 km당 {int(round(pace_gap))}초만 더 끌어올리면 닿는 거리예요."),
        {"predicted": _hms(pred), "target": _hms(target), "behind_s": int(round(behind)),
         "pace_gap_s": int(round(pace_gap)), "goal_km": round(goal_km, 1)},
        min(0.8, 0.4 + behind / 600),
        (f"예상 {_hms(pred)}가 목표 {_hms(target)}보다 {int(round(behind))}초 뒤. "
         f"필요한 km당 {int(round(pace_gap))}초 향상폭과 현실적 훈련 처방 코칭."))]


def long_run_readiness(runs: List[dict], ctx: dict) -> List[dict]:
    """Long-run distance readiness vs weeks_remaining. For a marathon/half, the longest recent
    long run should approach a phase-appropriate share of race distance."""
    goal = ctx.get("goal") or {}
    goal_km = _event_km(goal)
    wr = _weeks_remaining(ctx)
    if not goal_km or goal_km < 21 or wr is None:
        return []
    today = ctx["today"]
    longs = [r for r in window(runs, today, -1, 42)
             if r.get("dist") and r.get("type") in ("long", "easy")]
    if not longs:
        return []
    longest = max(r["dist"] for r in longs)
    # phase-appropriate target: more weeks left → lower expected share
    if wr <= 3:
        need_ratio = 0.78
    elif wr <= 6:
        need_ratio = 0.68
    elif wr <= 10:
        need_ratio = 0.55
    else:
        need_ratio = 0.42
    need_km = goal_km * need_ratio
    ratio = longest / goal_km
    if longest < need_km - 0.5:  # not yet ready → handled by another detector
        return []
    return [card(
        "long_run_readiness", "consistency", "🛣️",
        f"롱런 {longest:.0f}km · 남은 {wr:.0f}주 기준 충분",
        (f"최근 6주 최장 롱런이 {longest:.0f}km로 목표 거리({goal_km:.0f}km)의 {ratio*100:.0f}%예요. "
         f"레이스까지 {wr:.0f}주 남은 시점에 필요한 {need_km:.0f}km를 이미 채웠어요."),
        {"longest_km": round(longest, 1), "goal_km": round(goal_km, 1),
         "ratio_pct": round(ratio * 100), "need_km": round(need_km, 1), "weeks_remaining": round(wr, 1)},
        min(0.85, 0.45 + ratio / 2),
        (f"최장 롱런 {longest:.0f}km(목표 {goal_km:.0f}km의 {ratio*100:.0f}%), 남은 {wr:.0f}주 기준 충분. "
         f"테이퍼/추가 자극 타이밍 코칭."))]


def long_run_shortfall(runs: List[dict], ctx: dict) -> List[dict]:
    """The opposite of readiness: too few weeks left for how short the longest long run is.
    Warning-toned nudge to extend long runs while there's still runway."""
    goal = ctx.get("goal") or {}
    goal_km = _event_km(goal)
    wr = _weeks_remaining(ctx)
    if not goal_km or goal_km < 21 or wr is None:
        return []
    today = ctx["today"]
    longs = [r for r in window(runs, today, -1, 56)
             if r.get("dist") and r.get("type") in ("long", "easy")]
    if not longs:
        return []
    longest = max(r["dist"] for r in longs)
    if wr <= 3:
        need_ratio = 0.78
    elif wr <= 6:
        need_ratio = 0.68
    elif wr <= 10:
        need_ratio = 0.55
    else:
        return []  # plenty of runway → not a concern yet
    need_km = goal_km * need_ratio
    short = need_km - longest
    if short < 3.0:  # within range → no warning
        return []
    return [card(
        "long_run_shortfall", "warning", "📏",
        f"롱런 {short:.0f}km 부족 · 남은 {wr:.0f}주",
        (f"레이스까지 {wr:.0f}주 남았는데 최근 최장 롱런은 {longest:.0f}km예요. "
         f"이 시점 권장치 {need_km:.0f}km(목표 {goal_km:.0f}km의 {need_ratio*100:.0f}%)까지 "
         f"{short:.0f}km 더 늘려둘 필요가 있어요."),
        {"longest_km": round(longest, 1), "need_km": round(need_km, 1), "short_km": round(short, 1),
         "goal_km": round(goal_km, 1), "weeks_remaining": round(wr, 1)},
        min(0.85, 0.5 + short / 20),
        (f"롱런 {longest:.0f}km로 권장 {need_km:.0f}km보다 {short:.0f}km 부족, 남은 {wr:.0f}주. "
         f"무리 없이 롱런 거리 늘리는 점증 계획 코칭."))]


def longest_run_share(runs: List[dict], ctx: dict) -> List[dict]:
    """Longest run as a share of goal distance — a milestone signal when the runner first
    crosses meaningful fractions (60% / 75% / 90%) of race distance."""
    goal = ctx.get("goal") or {}
    goal_km = _event_km(goal)
    if not goal_km:
        return []
    today = ctx["today"]
    longs = [r for r in window(runs, today, -1, 35) if r.get("dist")]
    prior = [r for r in runs if r.get("dist") and age(r, today) > 35]
    if not longs:
        return []
    longest = max(longs, key=lambda r: r["dist"])
    cur_share = longest["dist"] / goal_km
    prev_best = max((r["dist"] for r in prior), default=0.0)
    prev_share = prev_best / goal_km if prev_best else 0.0
    # find the highest milestone newly crossed in the recent window
    crossed = None
    for m in (0.90, 0.75, 0.60):
        if cur_share >= m and prev_share < m:
            crossed = m
            break
    if crossed is None:
        return []
    return [card(
        "longest_run_share", "pr", "🏔️",
        f"목표 거리의 {int(crossed*100)}% 돌파 ({longest['dist']:.0f}km)",
        (f"{longest['dist']:.0f}km를 달리며 목표 거리({goal_km:.0f}km)의 {cur_share*100:.0f}%를 처음 넘었어요. "
         f"완주에 필요한 지구력이 눈에 보이게 쌓이고 있어요."),
        {"longest_km": round(longest["dist"], 1), "goal_km": round(goal_km, 1),
         "share_pct": round(cur_share * 100), "milestone_pct": int(crossed * 100),
         "date": longest["date"].isoformat()},
        min(0.9, 0.45 + crossed / 2),
        (f"최장 {longest['dist']:.0f}km로 목표 {goal_km:.0f}km의 {int(crossed*100)}% 첫 돌파. "
         f"다음 거리 마일스톤과 페이스 운용 코칭."))]


def finish_projection_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Projected finish improving over time: predict goal-race time from recent long/tempo
    runs (Riegel) in the last 3 weeks vs 5–11 weeks ago. Surfaces a downward (faster) trend."""
    goal = ctx.get("goal") or {}
    goal_km = _event_km(goal)
    if not goal_km:
        return []
    today = ctx["today"]

    def proj(lo, hi):
        # use sustained efforts of decent length to project the race time
        cand = [r for r in window(runs, today, lo, hi)
                if r.get("dist") and r.get("pace_s") and r["dist"] >= min(8.0, goal_km * 0.35)
                and r.get("type") in ("long", "tempo", "easy")]
        if not cand:
            return None, 0
        # best single effort → predict full race distance
        preds = []
        for r in cand:
            sec_from = int(round(r["pace_s"] * r["dist"]))
            p = _riegel_predict(r["dist"], sec_from, goal_km)
            if p:
                preds.append(p)
        if not preds:
            return None, 0
        return min(preds), len(preds)

    recent, nr = proj(-1, 21)
    base, nb = proj(35, 77)
    if recent is None or base is None or nr < 1 or nb < 2:
        return []
    gain = base - recent  # positive = faster projected finish now
    if gain < 60:  # at least a minute of projected improvement
        return []
    return [card(
        "finish_projection_trend", "improvement", "⏱️",
        f"예상 완주 {int(round(gain))}초 단축",
        (f"최근 롱런·템포 기준 예상 완주 기록이 {_hms(recent)}로, 한두 달 전 추정({_hms(base)})보다 "
         f"{int(round(gain))}초 빨라졌어요. 목표를 향한 곡선이 제대로 우상향이에요."),
        {"projected_now": _hms(recent), "projected_then": _hms(base), "gain_s": int(round(gain)),
         "goal_km": round(goal_km, 1), "n_recent": nr, "n_base": nb},
        min(0.9, 0.5 + gain / 600),
        (f"예상 완주 {_hms(base)}→{_hms(recent)}로 {int(round(gain))}초 단축. "
         f"개선 추세 의미와 레이스 전략 코칭."))]


# ---------------------------------------------------------------------------
# formatting helpers (after detectors to keep module readable)
# ---------------------------------------------------------------------------

def _hms(sec) -> str:
    """Seconds → 'H:MM:SS' or 'M:SS' for race-length times."""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _pb_label(km) -> str:
    if km is None:
        return "PB"
    if abs(km - 5.0) < 0.3:
        return "5km"
    if abs(km - 10.0) < 0.5:
        return "10km"
    if abs(km - 21.0975) < 0.6:
        return "하프"
    if abs(km - 42.195) < 1.0:
        return "풀"
    return f"{km:.0f}km"


DETECTORS = [
    target_pace_gap,
    target_pace_gap_closing,
    predicted_race_time,
    predicted_race_gap,
    long_run_readiness,
    long_run_shortfall,
    longest_run_share,
    finish_projection_trend,
]
