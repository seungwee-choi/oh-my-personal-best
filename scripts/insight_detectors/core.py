"""Core insight detectors (the original six). All others live in sibling category modules
and follow the same contract — see ``_util`` for the detector/card spec."""
from __future__ import annotations

import statistics as _st
from collections import Counter
from typing import List

from insight_detectors._util import card, fmt_pace, window


def aerobic_efficiency(runs: List[dict], ctx: dict) -> List[dict]:
    """HERO: at the SAME heart rate, are easy runs getting faster? Matches easy/recovery/long
    runs in a ±6bpm band around the median easy HR; last ~5 weeks vs 8–20 weeks ago."""
    today = ctx["today"]
    easy = [r for r in runs if r["type"] in ("easy", "recovery", "long") and r["hr"] and r["pace_s"]]
    if len(easy) < 8:
        return []
    hrs = sorted(r["hr"] for r in easy)
    med = hrs[len(hrs) // 2]
    band = [r for r in easy if abs(r["hr"] - med) <= 6]
    recent, base = window(band, today, 0, 35), window(band, today, 56, 140)
    if len(recent) < 3 or len(base) < 3:
        return []
    rp, rh = _st.mean(r["pace_s"] for r in recent), _st.mean(r["hr"] for r in recent)
    bp, bh = _st.mean(r["pace_s"] for r in base), _st.mean(r["hr"] for r in base)
    delta = bp - rp
    if delta < 8 or abs(rh - bh) > 5:
        return []
    return [card(
        "aerobic_efficiency", "improvement", "📈",
        f"같은 심박, {int(round(delta))}초 빨라졌어요",
        (f"최근 한 달 이지런이 {round(rh)}bpm에서 {fmt_pace(rp)}/km예요. 두세 달 전 같은 심박"
         f"({round(bh)}bpm)엔 {fmt_pace(bp)}/km였으니 {int(round(delta))}초/km 빨라진 셈 — "
         f"유산소 엔진이 좋아졌다는 가장 확실한 신호예요."),
        {"recent_pace": fmt_pace(rp), "base_pace": fmt_pace(bp), "hr": round(rh),
         "delta_s": int(round(delta)), "n_recent": len(recent), "n_base": len(base)},
        min(1.0, 0.55 + delta / 80),
        (f"최근 한 달 이지런 평균 {round(rh)}bpm에 {fmt_pace(rp)}/km, 두세 달 전 같은 심박대"
         f"({round(bh)}bpm)엔 {fmt_pace(bp)}/km. 같은 심박에 {int(round(delta))}초/km 빨라진 유산소 효율 향상. "
         f"무엇이 이걸 만들었고 다음에 어떻게 활용할지 코칭."),
    )]


def self_prs(runs: List[dict], ctx: dict) -> List[dict]:
    """Self-relative records in the last 3 weeks (NOT segment PRs): longest run, fastest pace
    at 10km+, highest average cadence."""
    today = ctx["today"]
    recent = window(runs, today, -1, 21)
    prior = [r for r in runs if (today - r["date"]).days > 21]
    if not recent or len(prior) < 10:
        return []
    cards: List[dict] = []

    rl = max((r for r in recent if r["dist"]), key=lambda r: r["dist"], default=None)
    pl = max((r["dist"] for r in prior if r["dist"]), default=0)
    if rl and pl and rl["dist"] > pl:
        cards.append(card(
            "pr_longest", "pr", "🏅", f"최장 거리 {rl['dist']:.1f}km",
            f"기존 최장({pl:.1f}km)을 넘어선 새 최장 거리예요. 지구력 영역이 한 단계 넓어졌어요.",
            {"distance_km": round(rl["dist"], 1), "prev_km": round(pl, 1), "date": rl["date"].isoformat()},
            min(1.0, 0.5 + (rl["dist"] - pl) / pl),
            f"최근 {rl['dist']:.1f}km로 기존 최장 {pl:.1f}km 경신. 회복·다음 롱런 운영 코칭."))

    def fastest(sel):
        c = [r for r in sel if r["dist"] and r["dist"] >= 9.5 and r["pace_s"]]
        return min(c, key=lambda r: r["pace_s"], default=None)

    rf, pf = fastest(recent), fastest(prior)
    if rf and pf and rf["pace_s"] < pf["pace_s"]:
        cards.append(card(
            "pr_fast_long", "pr", "⚡", f"10km+ 최고 페이스 {fmt_pace(rf['pace_s'])}/km",
            (f"{rf['dist']:.1f}km를 {fmt_pace(rf['pace_s'])}/km로 — 10km 이상 거리에서 역대 가장 "
             f"빠른 페이스예요(이전 {fmt_pace(pf['pace_s'])}/km)."),
            {"pace": fmt_pace(rf["pace_s"]), "prev_pace": fmt_pace(pf["pace_s"]),
             "distance_km": round(rf["dist"], 1), "date": rf["date"].isoformat()},
            min(1.0, 0.5 + (pf["pace_s"] - rf["pace_s"]) / 60),
            f"10km+ 최고 페이스 경신({fmt_pace(rf['pace_s'])}/km, 이전 {fmt_pace(pf['pace_s'])}/km). 의미·다음 자극 코칭."))

    rc = max((r for r in recent if r["cad"]), key=lambda r: r["cad"], default=None)
    pc = max((r["cad"] for r in prior if r["cad"]), default=0)
    if rc and pc and rc["cad"] > pc:
        cards.append(card(
            "pr_cadence", "pr", "🦶", f"최고 케이던스 {rc['cad']} spm",
            f"역대 가장 높은 평균 케이던스예요(이전 {pc} spm). 회전수가 올라가면 접지 충격이 줄어 부상 위험도 낮아져요.",
            {"cadence": rc["cad"], "prev": pc, "date": rc["date"].isoformat()},
            min(1.0, 0.45 + (rc["cad"] - pc) / 20),
            f"평균 케이던스 최고치 {rc['cad']}spm(이전 {pc}). 폼 관점 의미·유지법 코칭."))
    return cards


def load_spike(runs: List[dict], ctx: dict) -> List[dict]:
    """Hidden fatigue: this week's volume vs the trailing 4-week average (acute:chronic ≥1.4)."""
    today = ctx["today"]

    def vol(lo, hi):
        return sum((r["dist"] or 0) for r in runs if lo < (today - r["date"]).days <= hi)

    acute, chronic = vol(0, 7), vol(7, 35) / 4.0
    if chronic <= 0 or acute <= 0:
        return []
    ratio = acute / chronic
    if ratio < 1.4:
        return []
    pct = int(round((ratio - 1) * 100))
    return [card(
        "load_spike", "warning", "⚠️", f"이번 주 부하 +{pct}%",
        (f"최근 7일 거리({acute:.0f}km)가 직전 4주 평균({chronic:.0f}km/주)보다 {pct}% 많아요. "
         f"좋은 자극이지만 수면·회복을 챙기고, 무릎·아킬레스 신호가 오면 강도부터 줄이세요."),
        {"acute_km": round(acute), "chronic_km": round(chronic), "ratio": round(ratio, 2)},
        min(0.95, 0.45 + (ratio - 1.4)),
        f"최근 7일 {acute:.0f}km로 4주 평균 {chronic:.0f}km/주 대비 {pct}% 급증(ACWR {ratio:.2f}). 부상 위험·회복 우선순위 코칭.")]


def consistency_weeks(runs: List[dict], ctx: dict) -> List[dict]:
    """Consecutive weeks with ≥3 runs — a rhythm/streak signal that rewards showing up."""
    import datetime as _dt
    today = ctx["today"]
    by_week = Counter(r["date"].isocalendar()[:2] for r in runs if r["dist"])
    streak = 0
    for step in range(0, 260):
        wk = (today - _dt.timedelta(days=7 * step)).isocalendar()[:2]
        n = by_week.get(wk, 0)
        if step == 0 and n < 3:
            continue
        if n >= 3:
            streak += 1
        else:
            break
    if streak < 3:
        return []
    return [card(
        "consistency_weeks", "consistency", "🔥", f"{streak}주 연속 주 3회+ 러닝",
        (f"{streak}주 연속으로 한 주에 3번 이상 달렸어요. 체력은 며칠의 빡센 훈련이 아니라 이런 꾸준함에서 "
         f"만들어져요 — 지금 리듬이 가장 큰 자산이에요."),
        {"weeks": streak}, min(0.9, 0.4 + streak / 20),
        f"{streak}주 연속 주3회+ 러닝 유지 중. 꾸준함 칭찬 + 번아웃 없이 이어갈 운영 코칭.")]


def cadence_trend(runs: List[dict], ctx: dict) -> List[dict]:
    """Average cadence rising over months — a quiet form improvement."""
    today = ctx["today"]
    cad = [r for r in runs if r["cad"]]
    recent = [r["cad"] for r in cad if (today - r["date"]).days <= 35]
    base = [r["cad"] for r in cad if 56 < (today - r["date"]).days <= 140]
    if len(recent) < 5 or len(base) < 5:
        return []
    dr = _st.mean(recent) - _st.mean(base)
    if dr < 3:
        return []
    return [card(
        "cadence_trend", "improvement", "🦶", f"케이던스 +{int(round(dr))} spm",
        (f"평균 케이던스가 두세 달 전 {round(_st.mean(base))}spm에서 {round(_st.mean(recent))}spm로 올랐어요. "
         f"보폭을 줄이고 회전을 높이는 방향 — 효율과 부상 예방 모두에 좋은 변화예요."),
        {"recent": round(_st.mean(recent)), "base": round(_st.mean(base)), "delta": int(round(dr))},
        min(0.8, 0.35 + dr / 25),
        f"평균 케이던스 {round(_st.mean(base))}→{round(_st.mean(recent))}spm 상승. 폼 변화 의미 코칭.")]


def hill_adaptation(runs: List[dict], ctx: dict) -> List[dict]:
    """Climbing economy: a recent hilly run held a pace close to the flat-run average."""
    today = ctx["today"]
    recent_hilly = [r for r in runs
                    if (today - r["date"]).days <= 45 and r["ascent"] and r["dist"] and r["pace_s"]
                    and r["ascent"] / r["dist"] >= 12]
    flat = [r for r in runs
            if r["ascent"] is not None and r["dist"] and r["pace_s"]
            and r["ascent"] / max(r["dist"], 1) < 5 and r["type"] in ("easy", "recovery", "long")
            and (today - r["date"]).days <= 120]
    if not recent_hilly or len(flat) < 5:
        return []
    flat_pace = _st.median(r["pace_s"] for r in flat)
    h = max(recent_hilly, key=lambda r: r["ascent"])
    if h["pace_s"] - flat_pace > 20:
        return []
    return [card(
        "hill_adaptation", "adaptation", "⛰️", f"오르막 {int(h['ascent'])}m인데 평지 페이스",
        (f"{h['dist']:.1f}km에 누적 상승 {int(h['ascent'])}m를 {fmt_pace(h['pace_s'])}/km로 — "
         f"평지 이지런 평균({fmt_pace(flat_pace)}/km)과 거의 같아요. 언덕에 확실히 적응했다는 뜻이에요."),
        {"ascent_m": int(h["ascent"]), "pace": fmt_pace(h["pace_s"]), "flat_pace": fmt_pace(flat_pace),
         "distance_km": round(h["dist"], 1), "date": h["date"].isoformat()},
        0.5 + min(0.3, h["ascent"] / 1500),
        f"{h['dist']:.1f}km/상승 {int(h['ascent'])}m를 {fmt_pace(h['pace_s'])}/km(평지 평균 {fmt_pace(flat_pace)}/km)로 주파. 언덕 적응 의미·활용 코칭.")]


DETECTORS = [aerobic_efficiency, self_prs, load_spike, consistency_weeks, cadence_trend, hill_adaptation]
