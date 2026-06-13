"""Pace-execution insight detectors — how well a runner controls and distributes pace:
negative-split habit, interval pace consistency (CV), late-run fade, finishing kick,
tempo plan-vs-actual accuracy, and pacing-discipline trend. Follows the detector/card
contract in ``_util`` (see ``core`` for examples)."""
from __future__ import annotations

import statistics as _st
from typing import List, Optional

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


def _laps(ctx: dict, run: dict) -> Optional[List[dict]]:
    """Return clean lap_series for a run from ctx['deep'], or None."""
    if not run:
        return None
    deep = ctx.get("deep") or {}
    sid = run.get("source_id")
    if not sid or sid not in deep:
        return None
    analyze = deep.get(sid) or {}
    laps = analyze.get("lap_series")
    if not isinstance(laps, list) or len(laps) < 2:
        return None
    clean = []
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        p = lap.get("pace")
        if isinstance(p, (int, float)) and p > 0:
            clean.append(lap)
    return clean if len(clean) >= 2 else None


def _cv(vals: List[float]) -> Optional[float]:
    """Coefficient of variation (stdev/mean) for a list of positive numbers."""
    vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
    if len(vals) < 2:
        return None
    m = _st.mean(vals)
    if m <= 0:
        return None
    return _st.pstdev(vals) / m


def negative_split_habit(runs: List[dict], ctx: dict) -> List[dict]:
    """How often does the runner finish faster than they start? Looks at deep lap_series
    for recent runs and counts those where the back half is faster than the front half."""
    today = ctx["today"]
    recent = window(runs, today, -1, 60)
    splits = []  # (run, front_pace, back_pace)
    for r in recent:
        laps = _laps(ctx, r)
        if not laps:
            continue
        n = len(laps)
        half = n // 2
        if half < 1:
            continue
        front = [l["pace"] for l in laps[:half]]
        back = [l["pace"] for l in laps[half:]]
        fp, bp = mean(front), mean(back)
        if fp is None or bp is None:
            continue
        splits.append((r, fp, bp))
    if len(splits) < 3:
        return []
    neg = [s for s in splits if s[2] < s[1] - 2]  # back at least 2s/km faster
    ratio = len(neg) / len(splits)
    if ratio < 0.5 or len(neg) < 2:
        return []
    avg_gain = mean([s[1] - s[2] for s in neg])
    pct = int(round(ratio * 100))
    return [card(
        "negative_split_habit", "consistency", "📊",
        f"최근 달리기 {pct}%가 네거티브 스플릿",
        (f"최근 기록 {len(splits)}개 중 {len(neg)}개에서 후반이 전반보다 평균 "
         f"{int(round(avg_gain))}초/km 빨랐어요. 초반에 욕심내지 않고 끝까지 힘을 남기는 "
         f"좋은 페이싱 습관이 자리 잡았어요."),
        {"n_runs": len(splits), "n_negative": len(neg), "ratio_pct": pct,
         "avg_gain_s": int(round(avg_gain))},
        min(0.85, 0.45 + ratio * 0.4),
        (f"최근 {len(splits)}개 중 {len(neg)}개가 네거티브 스플릿(후반 평균 {int(round(avg_gain))}초/km 빠름). "
         f"끝까지 힘 남기는 페이싱 습관 칭찬 + 레이스에서 활용법 코칭."))]


def interval_pace_consistency(runs: List[dict], ctx: dict) -> List[dict]:
    """Interval repeat-pace evenness: among recent interval runs, is the lap-pace CV low?
    A low CV means each rep lands near the same pace — disciplined, controlled efforts."""
    today = ctx["today"]
    cands = [r for r in window(runs, today, -1, 45) if r.get("type") == "interval"]
    best = None  # (run, cv, n_laps, mean_pace)
    for r in cands:
        laps = _laps(ctx, r)
        if not laps or len(laps) < 4:
            continue
        paces = [l["pace"] for l in laps]
        cv = _cv(paces)
        if cv is None:
            continue
        if best is None or cv < best[1]:
            best = (r, cv, len(laps), _st.mean(paces))
    if best is None:
        return []
    r, cv, nlap, mp = best
    if cv > 0.04:  # >4% spread → not noteworthy
        return []
    cv_pct = round(cv * 100, 1)
    return [card(
        "interval_pace_consistency", "improvement", "🎯",
        f"인터벌 반복 페이스 편차 {cv_pct}%",
        (f"{r['date'].isoformat()} 인터벌에서 반복 구간 {nlap}개의 페이스 편차가 "
         f"{cv_pct}%(평균 {fmt_pace(mp)}/km)에 불과했어요. 매 반복을 거의 같은 속도로 "
         f"끊었다는 뜻 — 강도 조절 감각이 정교해졌어요."),
        {"cv_pct": cv_pct, "n_laps": nlap, "mean_pace": fmt_pace(mp),
         "date": r["date"].isoformat()},
        min(0.85, 0.5 + (0.04 - cv) * 8),
        (f"인터벌 {nlap}반복 페이스 CV {cv_pct}%(평균 {fmt_pace(mp)}/km)로 매우 균일. "
         f"페이스 컨트롤 감각 칭찬 + 이 균일함을 레이스 페이싱에 옮기는 코칭."))]


def interval_cv_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Are interval repeats getting MORE even over time? Compares lap-pace CV of recent
    interval runs vs older ones — a shrinking CV is improving pacing discipline."""
    today = ctx["today"]
    data = []  # (days_ago, cv)
    for r in runs:
        if r.get("type") != "interval":
            continue
        laps = _laps(ctx, r)
        if not laps or len(laps) < 4:
            continue
        cv = _cv([l["pace"] for l in laps])
        if cv is None:
            continue
        data.append((age(r, today), cv))
    recent = [cv for d, cv in data if d <= 35]
    base = [cv for d, cv in data if 35 < d <= 120]
    if len(recent) < 2 or len(base) < 2:
        return []
    rm, bm = _st.mean(recent), _st.mean(base)
    if bm <= 0 or rm >= bm:
        return []
    drop = (bm - rm) / bm
    if drop < 0.2:  # need a meaningful ≥20% reduction
        return []
    return [card(
        "interval_cv_trend", "improvement", "📉",
        f"인터벌 페이스 편차 {int(round(drop * 100))}% 감소",
        (f"인터벌 반복 페이스의 흔들림이 두세 달 전 {round(bm * 100, 1)}%에서 최근 "
         f"{round(rm * 100, 1)}%로 줄었어요. 같은 반복을 더 일정하게 끊고 있다는 뜻 — "
         f"페이스 컨트롤이 몸에 배고 있어요."),
        {"recent_cv_pct": round(rm * 100, 1), "base_cv_pct": round(bm * 100, 1),
         "drop_pct": int(round(drop * 100)), "n_recent": len(recent), "n_base": len(base)},
        min(0.8, 0.4 + drop),
        (f"인터벌 페이스 CV {round(bm * 100, 1)}%→{round(rm * 100, 1)}%로 {int(round(drop * 100))}% 감소. "
         f"반복 일관성이 좋아진 의미와 다음 강도 설계 코칭."))]


def late_run_fade(runs: List[dict], ctx: dict) -> List[dict]:
    """Late-run fade warning: a recent longer run where the last third slowed a lot vs
    the first third. Flags positive-split blowups so pacing can be reined in."""
    today = ctx["today"]
    recent = window(runs, today, -1, 30)
    worst = None  # (run, first_pace, last_pace, fade_s)
    for r in recent:
        if not (r.get("dist") and r["dist"] >= 8):
            continue
        laps = _laps(ctx, r)
        if not laps or len(laps) < 6:
            continue
        n = len(laps)
        third = max(1, n // 3)
        first = mean([l["pace"] for l in laps[:third]])
        last = mean([l["pace"] for l in laps[-third:]])
        if first is None or last is None:
            continue
        fade = last - first  # positive = slowed down
        if worst is None or fade > worst[3]:
            worst = (r, first, last, fade)
    if worst is None:
        return []
    r, fp, lp, fade = worst
    # only warn on a real blowup: ≥25s/km and ≥7% slowdown
    if fade < 25 or fp <= 0 or fade / fp < 0.07:
        return []
    pct = int(round(fade / fp * 100))
    return [card(
        "late_run_fade", "warning", "📉",
        f"후반 페이스 {int(round(fade))}초 느려짐",
        (f"{r['date'].isoformat()} {r['dist']:.1f}km에서 초반 {fmt_pace(fp)}/km로 출발했지만 "
         f"막판엔 {fmt_pace(lp)}/km까지 {int(round(fade))}초/km({pct}%) 느려졌어요. 초반 페이스가 "
         f"조금 빨랐을 수 있어요 — 다음엔 첫 1~2km를 의식적으로 눌러보세요."),
        {"first_pace": fmt_pace(fp), "last_pace": fmt_pace(lp), "fade_s": int(round(fade)),
         "fade_pct": pct, "distance_km": round(r["dist"], 1), "date": r["date"].isoformat()},
        min(0.75, 0.4 + fade / 120),
        (f"{r['dist']:.1f}km에서 후반 {int(round(fade))}초/km({pct}%) 페이드. 초반 오버페이스 가능성 진단 + "
         f"초반 억제·균등 분배 코칭."))]


def finishing_kick(runs: List[dict], ctx: dict) -> List[dict]:
    """Finishing kick: a recent run where the final kilometer was clearly faster than the
    run's average — evidence of a strong, controlled close with energy to spare."""
    today = ctx["today"]
    recent = window(runs, today, -1, 30)
    best = None  # (run, last_pace, body_pace, kick_s)
    for r in recent:
        if not (r.get("dist") and r["dist"] >= 5):
            continue
        laps = _laps(ctx, r)
        if not laps or len(laps) < 4:
            continue
        last = laps[-1]["pace"]
        body = mean([l["pace"] for l in laps[:-1]])
        if body is None or last <= 0:
            continue
        kick = body - last  # positive = final lap faster than the rest
        if best is None or kick > best[3]:
            best = (r, last, body, kick)
    if best is None:
        return []
    r, last, body, kick = best
    # meaningful kick: final km ≥12s/km faster and ≥4% faster than the body
    if kick < 12 or body <= 0 or kick / body < 0.04:
        return []
    pct = int(round(kick / body * 100))
    return [card(
        "finishing_kick", "improvement", "🚀",
        f"마지막 1km {int(round(kick))}초 가속",
        (f"{r['date'].isoformat()} {r['dist']:.1f}km에서 마지막 구간을 {fmt_pace(last)}/km로 "
         f"끊었어요. 본 구간 평균({fmt_pace(body)}/km)보다 {int(round(kick))}초/km({pct}%) 빠른 "
         f"마무리 — 끝에 힘을 남겨 밀어붙이는 좋은 신호예요."),
        {"last_pace": fmt_pace(last), "body_pace": fmt_pace(body), "kick_s": int(round(kick)),
         "kick_pct": pct, "distance_km": round(r["dist"], 1), "date": r["date"].isoformat()},
        min(0.8, 0.45 + kick / 80),
        (f"{r['dist']:.1f}km 마지막 구간 {fmt_pace(last)}/km로 본 구간 평균보다 {int(round(kick))}초/km 가속. "
         f"여력 있는 마무리의 의미 + 레이스 후반 운영 코칭."))]


def tempo_plan_accuracy(runs: List[dict], ctx: dict) -> List[dict]:
    """Tempo plan-vs-actual accuracy: how close recent tempo runs landed to the goal/target
    pace. Tight matching means the runner can dial in a target pace on demand."""
    today = ctx["today"]
    goal = ctx.get("goal") or {}
    target_s = None
    tp = goal.get("target_pace")
    if isinstance(tp, str):
        clock = tp.strip().split("/")[0].strip()
        if ":" in clock:
            try:
                mm, ss = clock.split(":")
                target_s = int(mm) * 60 + int(ss)
            except (ValueError, TypeError):
                target_s = None
    elif isinstance(tp, (int, float)) and tp > 0:
        target_s = int(tp)
    if not target_s or target_s <= 0:
        return []
    tempos = [r for r in window(runs, today, -1, 45)
              if r.get("type") == "tempo" and r.get("pace_s")]
    if len(tempos) < 2:
        return []
    errs = [abs(r["pace_s"] - target_s) for r in tempos]
    avg_err = mean(errs)
    if avg_err is None or avg_err > 8:  # within ~8s/km of target
        return []
    last = max(tempos, key=lambda r: r["date"])
    return [card(
        "tempo_plan_accuracy", "consistency", "🎯",
        f"템포 페이스 목표와 ±{int(round(avg_err))}초",
        (f"최근 템포런 {len(tempos)}개의 평균 페이스가 목표 {fmt_pace(target_s)}/km에서 "
         f"±{int(round(avg_err))}초/km 안에 들어왔어요. 머릿속 목표 페이스를 몸으로 그대로 "
         f"재현하는 능력 — 레이스에서 가장 든든한 무기예요."),
        {"target_pace": fmt_pace(target_s), "avg_error_s": int(round(avg_err)),
         "n_tempo": len(tempos), "last_pace": fmt_pace(last["pace_s"])},
        min(0.85, 0.5 + (8 - avg_err) / 16),
        (f"템포 {len(tempos)}회 평균 오차 ±{int(round(avg_err))}초/km(목표 {fmt_pace(target_s)}/km). "
         f"목표 페이스 재현력 칭찬 + 레이스 페이싱 자신감 코칭."))]


def even_pacing_discipline(runs: List[dict], ctx: dict) -> List[dict]:
    """Pacing discipline on steady runs: among recent easy/long runs with lap data, how even
    is the within-run pace? A low average lap CV shows controlled, metronomic pacing."""
    today = ctx["today"]
    cands = [r for r in window(runs, today, -1, 45)
             if r.get("type") in ("easy", "recovery", "long")]
    cvs = []
    for r in cands:
        laps = _laps(ctx, r)
        if not laps or len(laps) < 5:
            continue
        cv = _cv([l["pace"] for l in laps])
        if cv is not None:
            cvs.append(cv)
    if len(cvs) < 3:
        return []
    avg_cv = _st.mean(cvs)
    if avg_cv > 0.035:  # >3.5% within-run swing → not remarkable
        return []
    cv_pct = round(avg_cv * 100, 1)
    return [card(
        "even_pacing_discipline", "consistency", "📏",
        f"이지·롱런 페이스 흔들림 {cv_pct}%",
        (f"최근 이지·롱런 {len(cvs)}개에서 구간별 페이스 편차가 평균 {cv_pct}%에 그쳤어요. "
         f"기분이나 지형에 휘둘리지 않고 일정한 페이스를 유지하는 절제력이 좋아요 — "
         f"이게 부상 없이 거리를 쌓는 비결이에요."),
        {"avg_cv_pct": cv_pct, "n_runs": len(cvs)},
        min(0.75, 0.4 + (0.035 - avg_cv) * 9),
        (f"이지·롱런 {len(cvs)}개 평균 페이스 CV {cv_pct}%로 매우 균일. "
         f"페이스 절제력 칭찬 + 일정 페이스가 유산소 발달에 주는 이점 코칭."))]


def overpace_easy_warning(runs: List[dict], ctx: dict) -> List[dict]:
    """Easy-day discipline: are 'easy/recovery' runs being run too hard? Compares recent easy
    pace to the runner's tempo pace — easy runs creeping near tempo means polarization is off."""
    today = ctx["today"]
    easy = [r for r in window(runs, today, -1, 35)
            if r.get("type") in ("easy", "recovery") and r.get("pace_s")]
    tempo = [r for r in window(runs, today, -1, 60)
             if r.get("type") == "tempo" and r.get("pace_s")]
    if len(easy) < 4 or len(tempo) < 2:
        return []
    easy_med = median([r["pace_s"] for r in easy])
    tempo_med = median([r["pace_s"] for r in tempo])
    if easy_med is None or tempo_med is None or tempo_med <= 0:
        return []
    gap = easy_med - tempo_med  # how much slower easy is than tempo
    # healthy easy runs sit well above tempo; flag when within ~45s/km of tempo
    if gap >= 45:
        return []
    pct = int(round(gap / tempo_med * 100))
    return [card(
        "overpace_easy_warning", "warning", "🐢",
        f"이지런이 템포보다 {int(round(gap))}초밖에 안 느려요",
        (f"최근 이지·회복런 중앙값이 {fmt_pace(easy_med)}/km로, 템포 페이스"
         f"({fmt_pace(tempo_med)}/km)보다 {int(round(gap))}초/km({pct}%)밖에 느리지 않아요. "
         f"쉬운 날을 너무 빠르게 달리면 강약 대비가 무너져 회복도 자극도 어중간해져요 — "
         f"이지런은 더 과감하게 늦춰도 됩니다."),
        {"easy_pace": fmt_pace(easy_med), "tempo_pace": fmt_pace(tempo_med),
         "gap_s": int(round(gap)), "gap_pct": pct, "n_easy": len(easy)},
        min(0.7, 0.4 + (45 - gap) / 90),
        (f"이지 중앙값 {fmt_pace(easy_med)}/km가 템포 {fmt_pace(tempo_med)}/km와 {int(round(gap))}초/km밖에 차이 안 남. "
         f"양극화 훈련(쉬운 날은 더 쉽게) 필요성 코칭."))]


DETECTORS = [
    negative_split_habit,
    interval_pace_consistency,
    interval_cv_trend,
    late_run_fade,
    finishing_kick,
    tempo_plan_accuracy,
    even_pacing_discipline,
    overpace_easy_warning,
]
