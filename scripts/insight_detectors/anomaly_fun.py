"""Anomaly + fun insight detectors ("anomaly_fun" category).

Surprising, delightful one-off signals: first/rare negative split, an unusually low-HR day
for a given pace, a near-perfect even split (deep), the fastest finish (closing kick),
a surprise long run, calorie milestones, and an RPE/pace mismatch.

All follow the detector/card contract in ``_util``: ``def f(runs, ctx) -> list[card]``,
never raise, guard for None and small samples, surface a card only past a meaningful threshold.
"""
from __future__ import annotations

from typing import List

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


def first_negative_split(runs: List[dict], ctx: dict) -> List[dict]:
    """First (or rare) deep-confirmed negative split: the second half noticeably faster than the
    first. Uses lap_series from a recent deep run; counts how rare it is across known deep runs."""
    try:
        today = ctx["today"]
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        recent = window(runs, today, -1, 21)
        if not recent:
            return []

        def neg_split_gap(analyze):
            laps = (analyze or {}).get("lap_series") or []
            laps = [l for l in laps if l and l.get("pace") is not None]
            if len(laps) < 4:
                return None
            half = len(laps) // 2
            first = mean(l["pace"] for l in laps[:half])
            second = mean(l["pace"] for l in laps[half:])
            if first is None or second is None:
                return None
            return first - second  # >0 means second half faster

        # how often any deep run was a clear negative split (>=8s/km faster second half)
        neg_count = 0
        total = 0
        for a in deep.values():
            g = neg_split_gap(a)
            if g is None:
                continue
            total += 1
            if g >= 8:
                neg_count += 1
        if total == 0:
            return []

        # pick the best recent negative split
        best = None
        best_gap = 0.0
        for r in recent:
            a = deep.get(r.get("source_id"))
            g = neg_split_gap(a)
            if g is not None and g > best_gap:
                best, best_gap = r, g
        if best is None or best_gap < 10:
            return []

        rare = neg_count <= max(1, total // 4)
        head = "후반이 더 빨랐어요" if not rare else "드문 네거티브 스플릿"
        return [card(
            "first_negative_split", "improvement", "🚀",
            f"후반 {int(round(best_gap))}초 더 빠른 마무리",
            (f"{best['dist']:.1f}km를 달리며 후반 절반을 전반보다 km당 {int(round(best_gap))}초 더 빠르게 "
             f"달렸어요. 페이스를 아껴 두었다가 뒤에서 쏟아내는 네거티브 스플릿은 레이스에서 가장 강한 "
             f"전략이에요" + ("." if not rare else f" — 기록상 {total}번 중 {neg_count}번뿐인 드문 패턴이에요.")),
            {"gap_s": int(round(best_gap)), "distance_km": round(best["dist"], 1) if best.get("dist") else None,
             "neg_count": neg_count, "deep_total": total, "date": best["date"].isoformat()},
            min(0.95, 0.55 + best_gap / 60 + (0.1 if rare else 0.0)),
            (f"후반 절반이 전반보다 {int(round(best_gap))}초/km 빠른 네거티브 스플릿(기록 {total}건 중 {neg_count}건). "
             f"페이스 배분 칭찬 + 레이스 적용법 코칭. headline 톤: {head}."))]
    except Exception:
        return []


def low_hr_for_pace(runs: List[dict], ctx: dict) -> List[dict]:
    """An unusually efficient day: a recent run held a normal pace at a markedly lower HR than the
    runner's usual HR at that pace band. HR/pace only on the ~40% that have both."""
    try:
        today = ctx["today"]
        have = [r for r in runs if has(r, "hr", "pace_s", "dist") and r["dist"] >= 3
                and r["type"] in ("easy", "recovery", "long", "tempo")]
        if len(have) < 10:
            return []
        recent = [r for r in have if age(r, today) <= 21]
        if not recent:
            return []
        best = None
        best_drop = 0.0
        best_usual = None
        for r in recent:
            # peers within a tight pace band (+-12 s/km), excluding the run itself, older history
            peers = [p for p in have if p is not r and age(p, today) > 3
                     and abs(p["pace_s"] - r["pace_s"]) <= 12]
            if len(peers) < 5:
                continue
            usual = median(p["hr"] for p in peers)
            if usual is None:
                continue
            drop = usual - r["hr"]
            if drop > best_drop:
                best, best_drop = r, drop
                best_usual = usual
        if best is None or best_drop < 6:
            return []
        return [card(
            "low_hr_for_pace", "improvement", "💚",
            f"같은 페이스인데 심박 {int(round(best_drop))}bpm 낮은 날",
            (f"{fmt_pace(best['pace_s'])}/km로 달렸는데 평소 이 페이스의 심박({int(round(best_usual))}bpm)보다 "
             f"{int(round(best_drop))}bpm 낮은 {best['hr']}bpm이었어요. 컨디션이 좋았거나 회복이 잘 됐다는 "
             f"신호 — 몸이 같은 일을 더 적은 비용으로 해낸 날이에요."),
            {"pace": fmt_pace(best["pace_s"]), "hr": best["hr"], "usual_hr": int(round(best_usual)),
             "drop_bpm": int(round(best_drop)), "date": best["date"].isoformat()},
            min(0.85, 0.4 + best_drop / 30),
            (f"{fmt_pace(best['pace_s'])}/km에 심박 {best['hr']}bpm으로 평소({int(round(best_usual))}bpm)보다 "
             f"{int(round(best_drop))}bpm 낮음. 컨디션·회복·수면 요인 짚고 좋은 날 활용법 코칭."))]
    except Exception:
        return []


def perfect_even_split(runs: List[dict], ctx: dict) -> List[dict]:
    """Near-perfect even pacing on a recent deep run: very low spread across kilometre laps.
    Rewards metronomic discipline (great for long/tempo efforts)."""
    try:
        today = ctx["today"]
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        recent = window(runs, today, -1, 21)
        best = None
        best_cv = None
        best_mean = None
        best_n = None
        for r in recent:
            a = deep.get(r.get("source_id"))
            laps = (a or {}).get("lap_series") or []
            paces = [l["pace"] for l in laps if l and l.get("pace") is not None]
            if len(paces) < 5:
                continue
            m = mean(paces)
            if not m:
                continue
            # population-style spread: max deviation from mean in seconds
            spread = max(abs(p - m) for p in paces)
            if best_cv is None or spread < best_cv:
                best, best_cv, best_mean, best_n = r, spread, m, len(paces)
        if best is None or best_cv > 6:
            return []
        return [card(
            "perfect_even_split", "consistency", "🎯",
            f"{best_n}개 구간 편차 ±{int(round(best_cv))}초",
            (f"{best['dist']:.1f}km 내내 매 km 페이스가 평균 {fmt_pace(best_mean)}/km에서 최대 "
             f"{int(round(best_cv))}초 안쪽으로만 흔들렸어요. 사람이 메트로놈처럼 달리기는 정말 어려운데 — "
             f"페이스 감각이 몸에 박혔다는 증거예요."),
            {"spread_s": int(round(best_cv)), "avg_pace": fmt_pace(best_mean), "laps": best_n,
             "distance_km": round(best["dist"], 1) if best.get("dist") else None,
             "date": best["date"].isoformat()},
            min(0.9, 0.55 + (6 - best_cv) / 12),
            (f"{best_n}개 km 구간 페이스 편차 ±{int(round(best_cv))}초(평균 {fmt_pace(best_mean)}/km)로 거의 균등. "
             f"페이스 감각·레이스 페이싱 강점 코칭."))]
    except Exception:
        return []


def fastest_finish(runs: List[dict], ctx: dict) -> List[dict]:
    """A strong closing kick: the final lap of a recent deep run was the fastest of the run and
    well under its average — the ability to still push at the end."""
    try:
        today = ctx["today"]
        deep = ctx.get("deep") or {}
        if not deep:
            return []
        recent = window(runs, today, -1, 21)
        best = None
        best_kick = 0.0
        best_avg = None
        best_last = None
        for r in recent:
            a = deep.get(r.get("source_id"))
            laps = (a or {}).get("lap_series") or []
            paces = [l["pace"] for l in laps if l and l.get("pace") is not None]
            if len(paces) < 5:
                continue
            last = paces[-1]
            avg_rest = mean(paces[:-1])
            if avg_rest is None:
                continue
            # the last km must be the fastest of the run, kick = how much faster than the rest
            if last > min(paces[:-1]):
                continue
            kick = avg_rest - last
            if kick > best_kick:
                best, best_kick, best_avg, best_last = r, kick, avg_rest, last
        if best is None or best_kick < 12:
            return []
        return [card(
            "fastest_finish", "improvement", "🏁",
            f"마지막 1km {int(round(best_kick))}초 가속 마무리",
            (f"마지막 1km를 {fmt_pace(best_last)}/km로 — 그 전 구간 평균({fmt_pace(best_avg)}/km)보다 "
             f"{int(round(best_kick))}초 빠르게, 이 런에서 가장 빠른 구간으로 마무리했어요. 지친 다리로 "
             f"막판에 속도를 올릴 수 있다는 건 페이스에 여유가 있었다는 뜻이에요."),
            {"last_pace": fmt_pace(best_last), "avg_pace": fmt_pace(best_avg), "kick_s": int(round(best_kick)),
             "distance_km": round(best["dist"], 1) if best.get("dist") else None,
             "date": best["date"].isoformat()},
            min(0.85, 0.45 + best_kick / 50),
            (f"마지막 km {fmt_pace(best_last)}/km로 직전 평균 {fmt_pace(best_avg)}/km 대비 {int(round(best_kick))}초 "
             f"가속(최고 구간). 클로징 킥 강점·레이스 막판 운영 코칭."))]
    except Exception:
        return []


def surprise_long_run(runs: List[dict], ctx: dict) -> List[dict]:
    """A surprise long run: a recent run that ran far beyond the runner's typical distance — not
    necessarily a lifetime best, but a notable jump over the usual baseline."""
    try:
        today = ctx["today"]
        recent = [r for r in window(runs, today, -1, 14) if r.get("dist")]
        prior = [r["dist"] for r in runs if r.get("dist") and age(r, today) > 14]
        if not recent or len(prior) < 10:
            return []
        typ = median(prior)
        if not typ or typ <= 0:
            return []
        longest = max(recent, key=lambda r: r["dist"])
        ratio = longest["dist"] / typ
        # surprise = at least 60% longer than the usual run, and a real distance (>=8km)
        if ratio < 1.6 or longest["dist"] < 8:
            return []
        pct = int(round((ratio - 1) * 100))
        return [card(
            "surprise_long_run", "adaptation", "🗺️",
            f"평소보다 {pct}% 긴 {longest['dist']:.1f}km",
            (f"{longest['dist']:.1f}km를 달렸어요. 평소 한 번에 달리던 거리(중앙값 {typ:.1f}km)보다 {pct}% 더 "
             f"긴 거리예요. 계획에 없던 깜짝 롱런이라면 더 멋진 일 — 다만 다음 하루이틀은 회복을 넉넉히 두세요."),
            {"distance_km": round(longest["dist"], 1), "typical_km": round(typ, 1), "ratio": round(ratio, 2),
             "date": longest["date"].isoformat()},
            min(0.85, 0.4 + (ratio - 1.6) / 2),
            (f"{longest['dist']:.1f}km로 평소 중앙값 {typ:.1f}km보다 {pct}% 긴 롱런. 지구력 자극 의미 + 회복 코칭."))]
    except Exception:
        return []


def calorie_milestone(runs: List[dict], ctx: dict) -> List[dict]:
    """A cumulative-calorie milestone crossed recently: total kcal burned crossing a round
    threshold (10k, 25k, 50k, 100k, ...) — a fun all-time effort marker."""
    try:
        today = ctx["today"]
        cal_runs = [r for r in runs if r.get("cal") and r["cal"] > 0]
        if len(cal_runs) < 8:
            return []
        cal_runs = sorted(cal_runs, key=lambda r: r["date"])
        thresholds = [10000, 25000, 50000, 75000, 100000, 150000, 200000,
                      300000, 400000, 500000, 750000, 1000000]
        cum = 0
        crossed = None
        for r in cal_runs:
            before = cum
            cum += r["cal"]
            for t in thresholds:
                if before < t <= cum:
                    crossed = (t, r)  # keep the latest crossing
        if crossed is None:
            return []
        t, r = crossed
        # only surface if the crossing was recent enough to feel fresh
        if age(r, today) > 30:
            return []
        nice = f"{t:,}".replace(",", ",")
        return [card(
            "calorie_milestone", "consistency", "🔥",
            f"누적 {nice} kcal 돌파",
            (f"기록을 시작한 뒤 달리며 태운 칼로리가 총 {cum:,} kcal를 넘었어요. {nice} kcal는 한 걸음씩 "
             f"쌓아 올린 결과 — 눈에 안 보이지만 분명히 달라진 몸이 그 증거예요."),
            {"crossed_kcal": t, "total_kcal": int(cum), "date": r["date"].isoformat()},
            min(0.7, 0.35 + thresholds.index(t) / 30),
            (f"누적 소모 칼로리 {t:,}kcal 돌파(현재 총 {cum:,}kcal). 꾸준함의 누적 효과 격려 코칭."))]
    except Exception:
        return []


def rpe_pace_mismatch(runs: List[dict], ctx: dict) -> List[dict]:
    """RPE/pace mismatch: a recent run felt much easier than its pace would suggest (low RPE at a
    fast pace) — a sign of rising fitness or a great day. Uses runs that logged RPE."""
    try:
        today = ctx["today"]
        have = [r for r in runs if r.get("rpe") is not None and has(r, "pace_s", "dist")
                and r["dist"] >= 3 and r["type"] in ("easy", "recovery", "long", "tempo")]
        if len(have) < 10:
            return []
        recent = [r for r in have if age(r, today) <= 21]
        if not recent:
            return []
        best = None
        best_gap = 0.0
        best_usual = None
        for r in recent:
            # peers at a similar RPE (+-1) from older history
            peers = [p for p in have if p is not r and age(p, today) > 3
                     and abs((p["rpe"] or 0) - (r["rpe"] or 0)) <= 1]
            if len(peers) < 5:
                continue
            usual = median(p["pace_s"] for p in peers)
            if usual is None:
                continue
            gap = usual - r["pace_s"]  # >0 = faster than usual at this effort
            if gap > best_gap:
                best, best_gap, best_usual = r, gap, usual
        if best is None or best_gap < 12:
            return []
        return [card(
            "rpe_pace_mismatch", "improvement", "😎",
            f"체감 그대로인데 {int(round(best_gap))}초 빨랐어요",
            (f"RPE {best['rpe']}로 평소와 같은 힘만 줬는데 {fmt_pace(best['pace_s'])}/km가 나왔어요. 같은 "
             f"체감 강도의 평소 페이스({fmt_pace(best_usual)}/km)보다 km당 {int(round(best_gap))}초 빨라요 — "
             f"힘들이지 않고 더 빨라졌다는, 체력이 오를 때 나타나는 좋은 신호예요."),
            {"rpe": best["rpe"], "pace": fmt_pace(best["pace_s"]), "usual_pace": fmt_pace(best_usual),
             "gap_s": int(round(best_gap)), "date": best["date"].isoformat()},
            min(0.85, 0.45 + best_gap / 50),
            (f"RPE {best['rpe']}에 {fmt_pace(best['pace_s'])}/km로 같은 체감의 평소 {fmt_pace(best_usual)}/km보다 "
             f"{int(round(best_gap))}초 빠름. 체감 대비 능률 향상 의미 코칭."))]
    except Exception:
        return []


DETECTORS = [
    first_negative_split,
    low_hr_for_pace,
    perfect_even_split,
    fastest_finish,
    surprise_long_run,
    calorie_milestone,
    rpe_pace_mismatch,
]
