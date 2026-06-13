"""Form & cadence insight detectors.

Focus: speed-band cadence stability, long-run late-cadence fade (deep), high cadence
held at easy pace, cadence-pace coupling, and a stride-length proxy (speed/cadence).
Distinct from core ``cadence_trend`` (which only tracks month-over-month average cadence).
All detectors follow the standard contract in ``_util`` and never raise.
"""
from __future__ import annotations

import statistics as _st
from typing import List

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


def cadence_stability_by_speed(runs: List[dict], ctx: dict) -> List[dict]:
    """Easy-pace cadence consistency: low spread in spm across easy/recovery runs means a
    repeatable, locked-in form. Surfaces when the recent easy-run cadence stays tight."""
    try:
        today = ctx["today"]
        easy = [r for r in window(runs, today, -1, 56)
                if r["type"] in ("easy", "recovery") and has(r, "cad", "pace_s")]
        if len(easy) < 6:
            return []
        cads = [r["cad"] for r in easy]
        avg = mean(cads)
        sd = _st.pstdev(cads)
        if avg is None or avg <= 0:
            return []
        cv = sd / avg
        # Tight spread only: <2% coefficient of variation on >=6 easy runs.
        if cv >= 0.02 or sd > 3.2:
            return []
        return [card(
            "cadence_stability_easy", "consistency", "🎯",
            f"이지런 케이던스 ±{sd:.1f}spm로 일정",
            (f"최근 8주 이지런 {len(easy)}회의 평균 케이던스가 {round(avg)}spm, 편차는 "
             f"±{sd:.1f}spm뿐이에요. 달릴 때마다 같은 회전수를 재현한다는 건 폼이 몸에 "
             f"배었다는 뜻이라 페이스 흔들림과 부상 위험이 함께 줄어요."),
            {"avg_cadence": round(avg), "sd": round(sd, 1), "cv_pct": round(cv * 100, 1),
             "n": len(easy)},
            min(0.78, 0.45 + (0.02 - cv) * 18),
            (f"이지런 {len(easy)}회 평균 {round(avg)}spm, 편차 ±{sd:.1f}spm으로 케이던스가 "
             f"매우 안정적. 폼 자동화 의미와 이 안정성을 페이스 향상으로 연결하는 법 코칭."))]
    except Exception:
        return []


def long_run_cadence_fade(runs: List[dict], ctx: dict) -> List[dict]:
    """DEEP: in a recent long run, did cadence hold from the first third to the last third?
    Uses lap_series pace as a proxy when cadence laps are absent — but here we infer fade
    from the deep run's per-km structure, flagging when late laps slowed notably."""
    try:
        today = ctx["today"]
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        # Find the most recent long run that has deep data with enough laps.
        cand = [r for r in window(runs, today, -1, 30)
                if r["type"] == "long" and r.get("source_id") in deep]
        if not cand:
            return []
        cand.sort(key=lambda r: r["date"], reverse=True)
        run = cand[0]
        an = deep.get(run["source_id"]) or {}
        laps = an.get("lap_series") or []
        laps = [l for l in laps if isinstance(l, dict) and l.get("pace") is not None]
        if len(laps) < 9:
            return []
        third = max(2, len(laps) // 3)
        early = [l["pace"] for l in laps[:third]]
        late = [l["pace"] for l in laps[-third:]]
        e, lt = mean(early), mean(late)
        if e is None or lt is None:
            return []
        fade = lt - e  # positive = slower (higher sec/km) late = fade
        # Meaningful late-run fade only: >=18 s/km slower in the final third.
        if fade < 18:
            return []
        return [card(
            "long_run_late_fade", "warning", "📉",
            f"롱런 후반 {int(round(fade))}초/km 느려졌어요",
            (f"최근 {run['dist']:.0f}km 롱런에서 초반 {third}km는 {fmt_pace(e)}/km였는데 마지막 "
             f"{third}km는 {fmt_pace(lt)}/km로 떨어졌어요. 후반 페이스 저하는 보통 케이던스가 "
             f"무너지고 보폭에 의존하기 시작했다는 신호 — 후반 회전수를 의식적으로 유지하면 개선돼요."),
            {"early_pace": fmt_pace(e), "late_pace": fmt_pace(lt), "fade_s": int(round(fade)),
             "laps": len(laps), "distance_km": round(run["dist"], 1) if run.get("dist") else None,
             "date": run["date"].isoformat()},
            min(0.82, 0.45 + fade / 90),
            (f"{run['dist']:.0f}km 롱런 후반 {int(round(fade))}초/km 저하(초반 {fmt_pace(e)}→후반 "
             f"{fmt_pace(lt)}). 후반 케이던스 유지·롱런 에너지 배분 코칭."))]
    except Exception:
        return []


def high_cadence_at_easy(runs: List[dict], ctx: dict) -> List[dict]:
    """High cadence even at easy pace — the hardest place to keep turnover up. Flags when
    recent easy/recovery runs hold a notably high cadence relative to their slow pace."""
    try:
        today = ctx["today"]
        easy = [r for r in window(runs, today, -1, 42)
                if r["type"] in ("easy", "recovery") and has(r, "cad", "pace_s")]
        if len(easy) < 4:
            return []
        avg_cad = mean(r["cad"] for r in easy)
        avg_pace = mean(r["pace_s"] for r in easy)
        if avg_cad is None or avg_pace is None:
            return []
        # Only meaningful when pace is genuinely easy (>=5:20/km) yet cadence is high (>=178).
        if avg_pace < 320 or avg_cad < 178:
            return []
        return [card(
            "high_cadence_easy", "improvement", "🦵",
            f"이지 페이스에 케이던스 {round(avg_cad)}spm",
            (f"최근 6주 이지런이 평균 {fmt_pace(avg_pace)}/km로 느긋한데도 케이던스는 "
             f"{round(avg_cad)}spm를 유지하고 있어요. 느릴 때 회전수를 높게 가져가는 건 가장 "
             f"어려운 폼 습관 — 빠른 날엔 더 자연스럽게 효율이 따라올 거예요."),
            {"avg_cadence": round(avg_cad), "avg_pace": fmt_pace(avg_pace), "n": len(easy)},
            min(0.8, 0.42 + (avg_cad - 178) / 40),
            (f"이지런 평균 {fmt_pace(avg_pace)}/km에 케이던스 {round(avg_cad)}spm 유지. 느린 페이스 "
             f"고회전의 의미와 부상 예방 효과 코칭."))]
    except Exception:
        return []


def cadence_pace_coupling(runs: List[dict], ctx: dict) -> List[dict]:
    """How tightly cadence rises with pace: a strong positive correlation between speed and
    cadence means the runner spins up turnover (not just stretches stride) to go faster."""
    try:
        today = ctx["today"]
        pts = [r for r in window(runs, today, -1, 90) if has(r, "cad", "pace_s")]
        if len(pts) < 8:
            return []
        cad = [r["cad"] for r in pts]
        # speed proxy: 1000/pace_s (m per sec). Higher speed should pair with higher cadence.
        spd = [1000.0 / r["pace_s"] for r in pts]
        if len(set(cad)) < 3 or len(set(spd)) < 3:
            return []
        # Pearson r (manual, so it works on any Python version).
        n = len(pts)
        mx, my = sum(spd) / n, sum(cad) / n
        sxx = sum((x - mx) ** 2 for x in spd)
        syy = sum((y - my) ** 2 for y in cad)
        sxy = sum((x - mx) * (y - my) for x, y in zip(spd, cad))
        if sxx <= 0 or syy <= 0:
            return []
        corr = sxy / (sxx ** 0.5 * syy ** 0.5)
        # Strong coupling only: r >= 0.6 across >=8 runs spanning multiple speeds.
        if corr < 0.6:
            return []
        slow = min(pts, key=lambda r: 1000.0 / r["pace_s"])
        fast = max(pts, key=lambda r: 1000.0 / r["pace_s"])
        return [card(
            "cadence_pace_coupling", "adaptation", "🔗",
            f"빠를수록 케이던스↑ (상관 {corr:.2f})",
            (f"최근 3개월 {len(pts)}회를 보면 페이스가 빨라질수록 케이던스가 함께 올라가요"
             f"(상관계수 {corr:.2f}). 느린 날 {slow['cad']}spm에서 빠른 날 {fast['cad']}spm로 — "
             f"보폭을 무리하게 늘리는 대신 회전수로 속도를 만드는, 부상에 강한 가속 패턴이에요."),
            {"corr": round(corr, 2), "slow_cad": slow["cad"], "fast_cad": fast["cad"],
             "slow_pace": fmt_pace(slow["pace_s"]), "fast_pace": fmt_pace(fast["pace_s"]),
             "n": len(pts)},
            min(0.8, 0.4 + (corr - 0.6) * 0.9),
            (f"페이스-케이던스 상관 {corr:.2f}, {slow['cad']}→{fast['cad']}spm. 회전수 기반 가속의 "
             f"장점과 인터벌에서의 활용 코칭."))]
    except Exception:
        return []


def stride_length_proxy(runs: List[dict], ctx: dict) -> List[dict]:
    """Stride-length proxy (speed/cadence): meters per step. A growing stride at the same
    cadence — earned via better push-off — shows up as more distance per step over time."""
    try:
        today = ctx["today"]

        def stride_m(r):
            # meters per minute = speed(m/s)*60; per step = that / cadence(spm).
            return (1000.0 / r["pace_s"]) * 60.0 / r["cad"]

        usable = [r for r in runs if has(r, "cad", "pace_s")
                  and r["type"] in ("easy", "recovery", "long")]
        recent = [r for r in usable if age(r, today) <= 35]
        base = [r for r in usable if 56 < age(r, today) <= 140]
        if len(recent) < 4 or len(base) < 4:
            return []
        rs = mean(stride_m(r) for r in recent)
        bs = mean(stride_m(r) for r in base)
        rc = mean(r["cad"] for r in recent)
        bc = mean(r["cad"] for r in base)
        if None in (rs, bs, rc, bc):
            return []
        gain_cm = (rs - bs) * 100.0
        # Only flag a stride GAIN that is not just cadence dropping (cadence held within 2spm).
        if gain_cm < 4 or (bc - rc) > 2:
            return []
        return [card(
            "stride_length_growth", "improvement", "📏",
            f"보폭 +{gain_cm:.0f}cm (케이던스 유지)",
            (f"이지·롱런 보폭이 두세 달 전 {bs*100:.0f}cm에서 {rs*100:.0f}cm로 {gain_cm:.0f}cm 늘었어요. "
             f"케이던스는 {round(bc)}→{round(rc)}spm로 거의 그대로니, 같은 회전수에 한 발이 더 멀리 "
             f"나간 것 — 추진력이 좋아져 같은 노력에 더 빨라지는 변화예요."),
            {"recent_stride_cm": round(rs * 100), "base_stride_cm": round(bs * 100),
             "gain_cm": round(gain_cm), "recent_cad": round(rc), "base_cad": round(bc),
             "n_recent": len(recent), "n_base": len(base)},
            min(0.82, 0.45 + gain_cm / 40),
            (f"보폭 {bs*100:.0f}→{rs*100:.0f}cm(+{gain_cm:.0f}cm), 케이던스 {round(bc)}→{round(rc)}spm 유지. "
             f"추진력 향상의 의미와 과보폭 주의점 코칭."))]
    except Exception:
        return []


def cadence_drop_under_fatigue(runs: List[dict], ctx: dict) -> List[dict]:
    """Form-under-fatigue warning: recent easy/long cadence sagging below the runner's own
    established easy-run baseline can signal accumulated fatigue or a slipping form habit."""
    try:
        today = ctx["today"]
        usable = [r for r in runs if has(r, "cad")
                  and r["type"] in ("easy", "recovery", "long")]
        recent = [r["cad"] for r in usable if age(r, today) <= 14]
        base = [r["cad"] for r in usable if 21 < age(r, today) <= 120]
        if len(recent) < 3 or len(base) < 6:
            return []
        rm = mean(recent)
        bm = median(base)
        if rm is None or bm is None:
            return []
        drop = bm - rm  # positive = cadence fell vs baseline
        # Meaningful drop only: >=4 spm below the runner's own baseline.
        if drop < 4:
            return []
        return [card(
            "cadence_fatigue_drop", "warning", "🛞",
            f"최근 케이던스 -{int(round(drop))}spm",
            (f"지난 2주 케이던스가 평균 {round(rm)}spm로, 평소 기준({round(bm)}spm)보다 "
             f"{int(round(drop))}spm 낮아요. 회전수가 떨어지면 보폭과 접지 충격이 커지기 쉬워요 — "
             f"피로가 쌓였는지 돌아보고, 짧고 빠른 스트라이드로 회전 감각을 되살려 보세요."),
            {"recent_cadence": round(rm), "base_cadence": round(bm), "drop": int(round(drop)),
             "n_recent": len(recent), "n_base": len(base)},
            min(0.75, 0.4 + drop / 25),
            (f"케이던스 {round(bm)}→{round(rm)}spm(-{int(round(drop))}). 피로 누적 가능성 점검과 "
             f"회전수 회복 드릴 코칭."))]
    except Exception:
        return []


DETECTORS = [
    cadence_stability_by_speed,
    long_run_cadence_fade,
    high_cadence_at_easy,
    cadence_pace_coupling,
    stride_length_proxy,
    cadence_drop_under_fatigue,
]
