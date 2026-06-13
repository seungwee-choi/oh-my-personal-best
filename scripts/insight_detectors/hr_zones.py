"""Heart-rate zone insight detectors (category: hr_zones).

These lean on ``ctx['deep']`` — a small map ``{source_id: analyze}`` covering only the
most recent ~4 runs — so zone signals are read as single recent-run observations rather
than long trends. Each ``analyze`` carries ``time_in_zone_pct{Z1..Z5}``, ``hard_efforts``,
``summary{distance_km, duration_s, avg_pace, avg_hr}`` and ``lap_series``.

HR data exists on only ~40% of runs; deep coverage is thinner still. Every detector guards
on sample presence and returns [] when the signal is absent or below a meaningful threshold.
Never raises. See ``_util`` for the detector/card contract.
"""
from __future__ import annotations

import statistics as _st
from typing import List, Optional

from insight_detectors._util import card, fmt_pace, window, age, mean, median, has


# --------------------------------------------------------------------------- helpers

def _deep_recent(runs: List[dict], ctx: dict) -> List[tuple]:
    """Recent deep runs as (run, analyze) pairs, newest first.

    Only returns pairs whose source_id is present in ctx['deep']. Defensive against
    missing deep map, missing source_id and non-dict analyze payloads.
    """
    deep = ctx.get("deep") or {}
    if not isinstance(deep, dict) or not deep:
        return []
    out = []
    for r in runs:
        sid = r.get("source_id")
        if not sid:
            continue
        a = deep.get(sid)
        if isinstance(a, dict) and a:
            out.append((r, a))
    out.sort(key=lambda ra: ra[0]["date"], reverse=True)
    return out


def _zones(a: dict) -> Optional[dict]:
    """Return time_in_zone_pct as {Z1..Z5: float} if it looks usable, else None."""
    z = a.get("time_in_zone_pct")
    if not isinstance(z, dict):
        return None
    out = {}
    for k in ("Z1", "Z2", "Z3", "Z4", "Z5"):
        v = z.get(k)
        out[k] = float(v) if isinstance(v, (int, float)) else 0.0
    total = sum(out.values())
    if total <= 0:
        return None
    # normalize to percentage points summing ~100 if values look like fractions
    if total <= 1.5:
        out = {k: v * 100.0 for k, v in out.items()}
    return out


def _summary(a: dict) -> dict:
    s = a.get("summary")
    return s if isinstance(s, dict) else {}


# --------------------------------------------------------------------------- detectors

def z2_base_dominant(runs: List[dict], ctx: dict) -> List[dict]:
    """Most recent deep easy/recovery/long run spent a high share in Z2 — clean aerobic base work."""
    try:
        pairs = _deep_recent(runs, ctx)
        for r, a in pairs:
            if r.get("type") not in ("easy", "recovery", "long"):
                continue
            if age(r, ctx["today"]) > 21:
                continue
            z = _zones(a)
            if not z:
                continue
            z2 = z["Z2"]
            z1 = z["Z1"]
            if z2 < 65:
                continue
            base = z1 + z2
            dist = (_summary(a).get("distance_km") or r.get("dist"))
            dist_txt = f"{float(dist):.1f}km " if isinstance(dist, (int, float)) else ""
            return [card(
                "z2_base_dominant", "improvement", "🫀",
                f"Z2 비중 {int(round(z2))}%, 깔끔한 유산소런",
                (f"가장 최근 {dist_txt}이지런에서 시간의 {int(round(z2))}%를 Z2(편안한 유산소 구간)에서 보냈어요. "
                 f"저강도 구간을 길게 깔아 두는 게 유산소 엔진을 키우는 가장 확실한 방법이에요."),
                {"z2_pct": round(z2, 1), "z1_pct": round(z1, 1), "base_pct": round(base, 1),
                 "date": r["date"].isoformat()},
                min(0.8, 0.4 + (z2 - 65) / 80),
                (f"최근 이지런 Z2 {int(round(z2))}%(Z1+Z2 {int(round(base))}%). 저강도 베이스의 의미와 "
                 f"이 비중을 꾸준히 유지하는 법 코칭."))]
    except Exception:
        return []
    return []


def z5_high_intensity_dose(runs: List[dict], ctx: dict) -> List[dict]:
    """Recent deep run logged real Z5 time — a meaningful top-end / VO2 stimulus that needs recovery."""
    try:
        pairs = _deep_recent(runs, ctx)
        for r, a in pairs:
            if age(r, ctx["today"]) > 21:
                continue
            z = _zones(a)
            if not z:
                continue
            z5 = z["Z5"]
            if z5 < 6:
                continue
            tiz = a.get("time_in_zone_s")
            z5_s = None
            if isinstance(tiz, dict) and isinstance(tiz.get("Z5"), (int, float)):
                z5_s = int(tiz["Z5"])
            mins_txt = f"약 {z5_s // 60}분 " if z5_s and z5_s >= 60 else ""
            return [card(
                "z5_high_intensity_dose", "adaptation", "🔥",
                f"Z5 고강도 {int(round(z5))}% 노출",
                (f"가장 최근 런에서 시간의 {int(round(z5))}%({mins_txt}분량)를 Z5 최고 강도 구간에서 보냈어요. "
                 f"심폐 상단을 자극하는 좋은 자극이지만, 이런 날 뒤엔 하루 이틀 이지·회복으로 갚아 주세요."),
                {"z5_pct": round(z5, 1), "z5_s": z5_s, "type": r.get("type"),
                 "date": r["date"].isoformat()},
                min(0.85, 0.45 + z5 / 30),
                (f"최근 런 Z5 {int(round(z5))}% 노출. 고강도 자극의 효과와 이후 회복 배치 코칭."))]
    except Exception:
        return []
    return []


def easy_run_z3_leak(runs: List[dict], ctx: dict) -> List[dict]:
    """Easy-labeled deep run leaked too much time into Z3+ — the classic 'too hard easy day' trap."""
    try:
        pairs = _deep_recent(runs, ctx)
        for r, a in pairs:
            if r.get("type") not in ("easy", "recovery"):
                continue
            if age(r, ctx["today"]) > 21:
                continue
            z = _zones(a)
            if not z:
                continue
            leak = z["Z3"] + z["Z4"] + z["Z5"]
            if leak < 40:
                continue
            low = z["Z1"] + z["Z2"]
            return [card(
                "easy_run_z3_leak", "warning", "🟠",
                f"이지런인데 Z3+ {int(round(leak))}%",
                (f"이지런으로 기록된 최근 런인데 시간의 {int(round(leak))}%가 Z3 이상으로 새어 나갔어요. "
                 f"이지데이는 Z1~Z2(편안한 호흡)로 눌러 둬야 다음 포인트 훈련을 제대로 소화할 수 있어요."),
                {"z3plus_pct": round(leak, 1), "z3_pct": round(z["Z3"], 1),
                 "low_pct": round(low, 1), "date": r["date"].isoformat()},
                min(0.8, 0.45 + (leak - 40) / 80),
                (f"이지런 Z3+ 누수 {int(round(leak))}%(저강도 {int(round(low))}%). 이지데이를 진짜 이지로 "
                 f"눌러야 하는 이유와 페이스 가이드 코칭."))]
    except Exception:
        return []
    return []


def zone_polarization(runs: List[dict], ctx: dict) -> List[dict]:
    """A recent run shows polarized distribution — plenty of easy (Z1+Z2) and hard (Z4+Z5),
    little 'gray zone' Z3. The textbook shape for a quality session."""
    try:
        pairs = _deep_recent(runs, ctx)
        for r, a in pairs:
            if age(r, ctx["today"]) > 21:
                continue
            z = _zones(a)
            if not z:
                continue
            easy = z["Z1"] + z["Z2"]
            hard = z["Z4"] + z["Z5"]
            gray = z["Z3"]
            # need a genuinely two-peaked shape, not just an all-easy run
            if not (easy >= 55 and hard >= 15 and gray <= 18):
                continue
            return [card(
                "zone_polarization", "improvement", "⚖️",
                f"양극화 분포: 이지 {int(round(easy))}% · 하드 {int(round(hard))}%",
                (f"최근 런이 저강도({int(round(easy))}%)와 고강도({int(round(hard))}%)로 또렷이 갈리고, "
                 f"애매한 Z3는 {int(round(gray))}%뿐이었어요. 회색지대를 줄인 이 양극화 패턴이 "
                 f"퀄리티 세션의 교과서적인 모양이에요."),
                {"easy_pct": round(easy, 1), "hard_pct": round(hard, 1),
                 "gray_z3_pct": round(gray, 1), "date": r["date"].isoformat()},
                min(0.8, 0.45 + (hard - 15) / 60 + (18 - gray) / 100),
                (f"최근 런 양극화(이지 {int(round(easy))}% / 하드 {int(round(hard))}% / Z3 {int(round(gray))}%). "
                 f"polarized 훈련의 의미와 주간 배치 코칭."))]
    except Exception:
        return []
    return []


def gray_zone_buildup(runs: List[dict], ctx: dict) -> List[dict]:
    """A recent run sat heavily in Z3 — neither easy enough to recover nor hard enough to adapt.
    The 'junk mileage' moderate-intensity trap."""
    try:
        pairs = _deep_recent(runs, ctx)
        for r, a in pairs:
            if age(r, ctx["today"]) > 21:
                continue
            # tempo/interval are *supposed* to live higher; only flag aerobic-intent runs
            if r.get("type") in ("tempo", "interval"):
                continue
            z = _zones(a)
            if not z:
                continue
            z3 = z["Z3"]
            if z3 < 45:
                continue
            return [card(
                "gray_zone_buildup", "warning", "🌫️",
                f"Z3 회색지대 {int(round(z3))}%",
                (f"최근 런의 {int(round(z3))}%가 Z3 회색지대에 머물렀어요. 이 강도는 회복엔 너무 세고 "
                 f"적응 자극엔 살짝 부족한 구간이라, 이지는 더 낮게·포인트는 더 또렷하게 가르는 게 좋아요."),
                {"z3_pct": round(z3, 1), "type": r.get("type"), "date": r["date"].isoformat()},
                min(0.75, 0.4 + (z3 - 45) / 80),
                (f"최근 런 Z3 정체 {int(round(z3))}%. 회색지대를 줄이고 강·약을 분리하는 방향 코칭."))]
    except Exception:
        return []
    return []


def max_hr_observation(runs: List[dict], ctx: dict) -> List[dict]:
    """Recent run reached a notably high max HR vs the runner's other HR runs — a near-ceiling
    effort worth recognizing (and recovering from)."""
    try:
        today = ctx["today"]
        recent_deep = _deep_recent(runs, ctx)
        if not recent_deep:
            return []
        # baseline of historical max_hr from all HR-bearing runs
        hist = [r["max_hr"] for r in runs if r.get("max_hr")]
        if len(hist) < 8:
            return []
        ceiling = max(hist)
        med_max = median(hist)
        if med_max is None:
            return []
        for r, a in recent_deep:
            if age(r, today) > 21:
                continue
            mh = r.get("max_hr")
            if not mh:
                continue
            # within 2 bpm of all-time ceiling and clearly above typical
            if mh >= ceiling - 2 and mh - med_max >= 6:
                return [card(
                    "max_hr_observation", "adaptation", "🚀",
                    f"최고 심박 {int(mh)}bpm 도달",
                    (f"최근 런에서 최고 심박이 {int(mh)}bpm까지 올라갔어요 — 평소 최고치 중앙값"
                     f"({int(round(med_max))}bpm)을 한참 웃도는, 거의 천장에 닿은 노력이에요. "
                     f"이런 날은 충분한 회복이 곧 다음 성장으로 이어져요."),
                    {"max_hr": int(mh), "ceiling": int(ceiling), "median_max": int(round(med_max)),
                     "date": r["date"].isoformat()},
                    min(0.8, 0.45 + (mh - med_max) / 40),
                    (f"최근 런 max HR {int(mh)}bpm(중앙값 {int(round(med_max))}). 상단 노력의 의미와 "
                     f"회복 우선 배치 코칭."))]
    except Exception:
        return []
    return []


def hard_efforts_burst(runs: List[dict], ctx: dict) -> List[dict]:
    """A recent deep run packed in multiple hard efforts (surges/reps) — a structured stimulus,
    surfaced from the analyze hard_efforts count."""
    try:
        today = ctx["today"]
        for r, a in _deep_recent(runs, ctx):
            if age(r, today) > 21:
                continue
            he = a.get("hard_efforts")
            if not isinstance(he, (int, float)):
                continue
            he = int(he)
            if he < 4:
                continue
            structure = a.get("structure")
            struct_txt = f" ({structure})" if isinstance(structure, str) and structure else ""
            dist = (_summary(a).get("distance_km") or r.get("dist"))
            dist_txt = f"{float(dist):.1f}km에서 " if isinstance(dist, (int, float)) else ""
            return [card(
                "hard_efforts_burst", "adaptation", "💥",
                f"하드 에포트 {he}회 소화",
                (f"최근 런에서 {dist_txt}{he}번의 고강도 구간{struct_txt}을 반복했어요. "
                 f"이렇게 강약을 또렷이 나눈 자극은 스피드와 젖산 내성을 동시에 끌어올려요."),
                {"hard_efforts": he, "structure": structure if isinstance(structure, str) else None,
                 "type": r.get("type"), "date": r["date"].isoformat()},
                min(0.8, 0.4 + he / 20),
                (f"최근 런 하드 에포트 {he}회{struct_txt}. 인터벌 자극의 효과와 회복·다음 세션 배치 코칭."))]
    except Exception:
        return []
    return []


def zone_discipline(runs: List[dict], ctx: dict) -> List[dict]:
    """Across the few recent deep runs, easy days stayed easy AND quality days hit their zones —
    a session-level discipline signal. Needs at least 3 deep runs to read intent vs execution."""
    try:
        today = ctx["today"]
        pairs = [(r, a) for (r, a) in _deep_recent(runs, ctx) if age(r, today) <= 28]
        if len(pairs) < 3:
            return []
        easy_ok = 0
        easy_total = 0
        quality_ok = 0
        quality_total = 0
        for r, a in pairs:
            z = _zones(a)
            if not z:
                continue
            t = r.get("type")
            if t in ("easy", "recovery"):
                easy_total += 1
                if (z["Z1"] + z["Z2"]) >= 75:  # truly easy
                    easy_ok += 1
            elif t in ("tempo", "interval"):
                quality_total += 1
                if (z["Z4"] + z["Z5"] + z["Z3"]) >= 35:  # actually got to work
                    quality_ok += 1
        # need both kinds represented to call it discipline
        if easy_total < 2 or quality_total < 1:
            return []
        if easy_ok < easy_total or quality_ok < quality_total:
            return []
        n = easy_total + quality_total
        return [card(
            "zone_discipline", "consistency", "🎯",
            f"최근 {n}런 강도 규율 100%",
            (f"최근 딥 분석된 {n}개 런에서 이지데이({easy_total}회)는 저강도로 눌렀고, "
             f"포인트 데이({quality_total}회)는 목표 강도까지 제대로 올렸어요. "
             f"강·약을 분명히 가르는 이 규율이 정체 없이 성장하게 만드는 핵심이에요."),
            {"easy_ok": easy_ok, "easy_total": easy_total,
             "quality_ok": quality_ok, "quality_total": quality_total, "n": n},
            min(0.8, 0.45 + n / 20),
            (f"최근 {n}런 강도 규율 양호(이지 {easy_ok}/{easy_total}, 포인트 {quality_ok}/{quality_total}). "
             f"강약 분리의 가치 칭찬 + 유지 코칭."))]
    except Exception:
        return []
    return []


DETECTORS = [
    z2_base_dominant,
    z5_high_intensity_dose,
    easy_run_z3_leak,
    zone_polarization,
    gray_zone_buildup,
    max_hr_observation,
    hard_efforts_burst,
    zone_discipline,
]
