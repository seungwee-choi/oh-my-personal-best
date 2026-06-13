"""체중·연료 추적 — ``body.jsonl`` 로그 + 추세 / 레이스 체중 / 연료 조언.

Stdlib-only. Part of the oh-my-personal-best deterministic toolkit (scripts/).
Writes to: $OMPB_HOME/body.jsonl (weight entries), $OMPB_HOME/fueling.jsonl (fuel checks),
           $OMPB_HOME/goal.json (target_weight_kg key only — race goal keys are preserved).

러너에게 칼로리 다이어리를 강요하지 않는다. 체중(정량 앵커)을 가볍게 추적하고(원탭 입력),
코치가 추세·레이스 체중·언더퓨얼링을 추론하도록 신호를 만든다. ``goal.json``의 ``race_date``
+ ``target_weight_kg``와 연동해 레이스 체중 진행률을 계산하고, 세션 유형별 결정론 연료 조언
(롱런 전 카브 / 인터벌 후 단백질)을 제공한다.

Pure + defensive: 파일이 없으면 ``None``/빈 결과를 돌려주고 절대 raise 하지 않는다.
저장 단위는 라인별 JSON(``body.jsonl``): ``{date, weight_kg, bodyfat_pct?, note?, source}``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics as _st
from typing import List, Optional

from ompb_env import local_today, resolve_home

# 안전 감량 상한 — 주당 체중의 1%. 이를 넘는 감량은 글리코겐·근손실·RED-S(상대적 에너지
# 부족) 위험 신호로 보고 코치가 강도를 낮추고 연료 점검을 권한다(스포츠영양 통념).
_SAFE_LOSS_PCT_WK = 0.01
# 주간 변화율 추정에 쓸 최근 구간(일) — 너무 길면 다이어트 국면 전환을 못 따라가고,
# 너무 짧으면 일일 변동(수분)에 휘둘린다.
_RATE_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# goal.json helpers (tiny local — no import of goal module to avoid circular)
# ---------------------------------------------------------------------------

def _read_goal(home: str) -> dict:
    """Read $OMPB_HOME/goal.json. Returns {} on missing or invalid JSON."""
    path = os.path.join(home, "goal.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_goal(home: str, obj: dict) -> None:
    """Merge ``obj`` into goal.json, preserving all existing keys.

    Only touches the keys present in ``obj``. Race goal fields (event, target_time,
    race_date, etc.) are never clobbered when only target_weight_kg is being written.
    """
    existing = _read_goal(home)
    merged = {**existing, **obj,
              "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "goal.json"), "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _home(home: Optional[str]) -> str:
    return home or resolve_home(create=True)


def _path(home: Optional[str]) -> str:
    return os.path.join(_home(home), "body.jsonl")


def _mean(vals) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return _st.mean(vals) if vals else None


def _load(home: Optional[str]) -> List[dict]:
    """``body.jsonl``의 모든 라인을 파싱해 dict 리스트로(입력 순서). 파일 없으면 ``[]``."""
    path = _path(home)
    if not os.path.isfile(path):
        return []
    rows: List[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def _weights(home: Optional[str]) -> List[tuple]:
    """``(date, weight_kg)`` 쌍을 날짜 오름차순으로. 파싱 불가/무게 없는 행은 제외."""
    out = []
    for r in _load(home):
        w = r.get("weight_kg")
        try:
            d = _dt.date.fromisoformat(str(r.get("date")))
        except (ValueError, TypeError):
            continue
        if isinstance(w, (int, float)):
            out.append((d, float(w)))
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# Weight log
# ---------------------------------------------------------------------------

def log_weight(home: Optional[str], weight_kg: float, *, bodyfat_pct: Optional[float] = None,
               note: Optional[str] = None, on_date: Optional[str] = None) -> dict:
    """체중 한 건을 ``body.jsonl``에 append(원탭 입력). ``on_date`` 미지정 시 KST 오늘.
    같은 날 여러 번 찍어도 막지 않는다(추세는 최신값/이동평균으로 흡수). 기록한 dict 반환."""
    home = _home(home)
    entry = {
        "date": on_date or local_today().isoformat(),
        "weight_kg": round(float(weight_kg), 1),
        "source": "manual",
        # 마이크로초까지 — 같은 초에 두 번 찍어도 고유키가 되어 delete_entry가 한 건만 지운다.
        "logged_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    if bodyfat_pct is not None:
        entry["bodyfat_pct"] = round(float(bodyfat_pct), 1)
    if note:
        entry["note"] = str(note).strip()[:200]
    os.makedirs(home, exist_ok=True)
    with open(_path(home), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def delete_entry(home: Optional[str], logged_at: str) -> bool:
    """``body.jsonl``에서 ``logged_at``이 일치하는 체중 기록을 제거(오기입 정정). 원자적 재작성.
    제거하면 True, 일치 항목이 없으면 False. ``logged_at``은 기록 시점 UTC 타임스탬프로 사실상 고유키."""
    home = _home(home)
    path = _path(home)
    if not logged_at or not os.path.isfile(path):
        return False
    rows = _load(home)
    keep = [r for r in rows if r.get("logged_at") != logged_at]
    if len(keep) == len(rows):
        return False
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in keep:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def _rate_kg_wk(weights: List[tuple], today: _dt.date, days: int = _RATE_WINDOW_DAYS) -> Optional[float]:
    """최근 ``days`` 구간의 주당 체중 변화율(kg/주, 음수=감량). 최소제곱 기울기로 추정 —
    측정 간격이 들쭉날쭉해도(원탭 입력) 안정적. 구간이 3일 미만이면 추정 불가(``None``)."""
    sel = [(d, w) for d, w in weights if (today - d).days <= days]
    if len(sel) < 2:
        return None
    x0 = sel[0][0]
    xs = [(d - x0).days for d, _ in sel]
    ys = [w for _, w in sel]
    if xs[-1] - xs[0] < 3:
        return None
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom  # kg/day
    return round(slope * 7, 2)


def trend(home: Optional[str]) -> Optional[dict]:
    """체중 추세 요약 — 현재값 / 7·30일 이동평균 / 주당 변화율 / 스파크라인. 데이터 없으면 ``None``."""
    weights = _weights(home)
    if not weights:
        return None
    today = local_today()
    cur_date, current = weights[-1]

    def _ma(days):
        sel = [w for d, w in weights if (today - d).days <= days]
        m = _mean(sel)
        return round(m, 1) if m is not None else None

    bodyfat = None
    for r in reversed(_load(home)):
        if isinstance(r.get("bodyfat_pct"), (int, float)):
            bodyfat = float(r["bodyfat_pct"])
            break
    return {
        "current": round(current, 1),
        "current_date": cur_date.isoformat(),
        "ma7": _ma(7),
        "ma30": _ma(30),
        "rate_kg_wk": _rate_kg_wk(weights, today),
        "bodyfat_pct": bodyfat,
        "n": len(weights),
        "spark": [round(w, 1) for _, w in weights[-14:]],
        "min": round(min(w for _, w in weights), 1),
        "max": round(max(w for _, w in weights), 1),
    }


def recent(home: Optional[str], limit: int = 30) -> List[dict]:
    """최근 체중 기록(최신순) — 카드의 '최근 기록' 미니 리스트용."""
    rows = [r for r in _load(home) if isinstance(r.get("weight_kg"), (int, float))]
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("logged_at") or "")), reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------
# Race weight / target
# ---------------------------------------------------------------------------

def target_weight(home: Optional[str]) -> Optional[float]:
    """``goal.json``의 목표 체중(kg). 없으면 ``None``."""
    g = _read_goal(_home(home))
    tw = g.get("target_weight_kg")
    return float(tw) if isinstance(tw, (int, float)) else None


def set_target_weight(home: Optional[str], kg: Optional[float]) -> Optional[float]:
    """목표 체중을 ``goal.json``에 병합 저장(기존 레이스 목표는 보존). ``kg=None``이면 해제."""
    resolved = _home(home)
    g = _read_goal(resolved)
    if kg is None:
        g.pop("target_weight_kg", None)
        _write_goal(resolved, g)
    else:
        _write_goal(resolved, {"target_weight_kg": round(float(kg), 1)})
    return _read_goal(resolved).get("target_weight_kg")


def race_weight(home: Optional[str]) -> Optional[dict]:
    """레이스 체중 진행 — 목표 체중(goal) + 현재 추세 + 레이스 날짜로 진행률/필요속도/안전성 계산.
    목표 체중 또는 체중 데이터가 없으면 ``None``. ``gap_kg``<0 = 더 빼야 함."""
    target = target_weight(home)
    t = trend(home)
    if target is None or not t:
        return None
    current = t["ma7"] or t["current"]
    gap = round(target - current, 1)  # 음수 = 감량 필요
    out: dict = {"current_kg": round(current, 1), "target_kg": round(target, 1), "gap_kg": gap}
    g = _read_goal(_home(home))
    race_date = g.get("race_date")
    if race_date:
        try:
            weeks = (_dt.date.fromisoformat(str(race_date)) - local_today()).days / 7.0
        except (ValueError, TypeError):
            weeks = None
        if weeks is not None:
            out["weeks_left"] = round(max(0.0, weeks), 1)
            if weeks > 0:
                weekly_needed = round(gap / weeks, 2)  # kg/주 (음수=감량)
                pct = abs(weekly_needed) / current if current else 0.0
                out["weekly_needed_kg_wk"] = weekly_needed
                out["safe"] = pct <= _SAFE_LOSS_PCT_WK
    out["on_track"] = abs(gap) < 0.3 or bool(out.get("safe", True))
    return out


# ---------------------------------------------------------------------------
# Under-fueling detection
# ---------------------------------------------------------------------------

def under_fueling_flag(home: Optional[str]) -> Optional[dict]:
    """실제 감량 속도가 주당 1%(체중)를 넘으면 언더퓨얼링 위험 신호. 아니면 ``None``.
    코치 가드레일(고부하+급감 → easy 바이어스)과 인사이트 경고 카드가 함께 쓴다."""
    t = trend(home)
    if not t or t.get("rate_kg_wk") is None or not t.get("current"):
        return None
    rate = t["rate_kg_wk"]  # kg/주, 음수=감량
    if rate >= 0:
        return None
    pct = abs(rate) / t["current"]
    if pct < _SAFE_LOSS_PCT_WK:
        return None
    return {
        "rate_kg_wk": rate,
        "pct_per_week": round(pct * 100, 1),
        "msg": (f"최근 감량 속도 주 {abs(rate)}kg ({round(pct * 100, 1)}%/주) — 권장 상한(1%/주) "
                "초과. 연료 섭취를 점검하고, 고강도 세션은 강도/볼륨을 보수적으로."),
    }


# ---------------------------------------------------------------------------
# Fuel log
# ---------------------------------------------------------------------------

def _fuel_path(home: Optional[str]) -> str:
    return os.path.join(_home(home), "fueling.jsonl")


def log_fuel(home: Optional[str], *, source_id: Optional[str] = None, day_type: Optional[str] = None,
             pre: bool = False, during: bool = False, post: bool = False,
             note: Optional[str] = None, on_date: Optional[str] = None) -> dict:
    """세션 연료 체크 한 건을 ``fueling.jsonl``에 append(롱런/하드 직후 3탭: 전·중·후).
    같은 세션(``source_id``)을 다시 찍으면 최신 라인이 우선(``fuel_for``가 최신을 읽음)."""
    home = _home(home)
    entry = {
        "date": on_date or local_today().isoformat(),
        "pre": bool(pre), "during": bool(during), "post": bool(post),
        "logged_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if source_id:
        entry["source_id"] = str(source_id)
    if day_type:
        entry["day_type"] = str(day_type)
    if note:
        entry["note"] = str(note).strip()[:200]
    os.makedirs(home, exist_ok=True)
    with open(_fuel_path(home), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _load_fuel(home: Optional[str]) -> List[dict]:
    path = _fuel_path(home)
    if not os.path.isfile(path):
        return []
    rows: List[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def fuel_for(home: Optional[str], source_id: str) -> Optional[dict]:
    """특정 세션의 가장 최근 연료 체크(중복 입력 시 마지막이 우선). 없으면 ``None``."""
    if not source_id:
        return None
    found = None
    for r in _load_fuel(home):
        if r.get("source_id") == source_id:
            found = r
    return found


def fuel_log(home: Optional[str], limit: int = 30) -> List[dict]:
    """최근 연료 체크(최신순). 코치 grounding / 디버그용."""
    rows = _load_fuel(home)
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("logged_at") or "")), reverse=True)
    return rows[:limit]


def fuel_advice(day_type: str = "") -> dict:
    """세션 유형별 결정론 연료 조언 — 전/후 섭취 가이드 + flags."""
    dt = (day_type or "").lower()
    if dt == "long":
        return {"label": "롱런 연료",
                "before": "2~3시간 전 탄수 위주 식사 · 90분↑이면 젤/이온음료 준비",
                "after": "30~60분 내 탄수+단백질(약 3:1)로 글리코겐 회복",
                "note": "롱런은 연료 게임 — 전 충전 · 중 보충 · 후 회복",
                "flags": ["pre_carb", "mid_fuel", "post_recovery"]}
    if dt in ("interval", "tempo", "race"):
        return {"label": "고강도 연료",
                "before": "1~2시간 전 가벼운 탄수 · 공복 고강도는 지양",
                "after": "단백질 위주 회복식으로 근손상 회복",
                "note": "고강도 전 연료 채우고 끝나고 단백질",
                "flags": ["pre_carb", "post_protein"]}
    if dt in ("easy", "recovery", "cross"):
        return {"label": "가벼운 세션", "before": "", "after": "",
                "note": "평소 식사로 충분 · 수분만 챙기기", "flags": []}
    return {"label": "", "before": "", "after": "", "note": "", "flags": []}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summary(home: Optional[str]) -> Optional[dict]:
    """코치 grounding / API용 압축 요약 — 추세 + 레이스 체중 + 언더퓨얼링 위험. 데이터 없으면 ``None``."""
    t = trend(home)
    if not t:
        return None
    out: dict = {"current_kg": t["current"], "ma7": t["ma7"],
                 "ma30": t["ma30"], "rate_kg_wk": t["rate_kg_wk"], "n": t["n"]}
    rw = race_weight(home)
    if rw:
        out["race_weight"] = rw
    uf = under_fueling_flag(home)
    if uf:
        out["under_fueling_risk"] = uf
    fuel = fuel_log(home, limit=8)
    if fuel:
        out["recent_fueling"] = [{k: f.get(k) for k in ("date", "day_type", "pre", "during", "post")}
                                 for f in fuel]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="body.py",
        description="체중·연료 추적 CLI — body.jsonl 로그 읽기/쓰기.",
    )
    ap.add_argument("--home", default=None, help="OMPB_HOME override (default: auto-resolve)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # log subcommand
    p_log = sub.add_parser("log", help="체중 기록 (append to body.jsonl)")
    p_log.add_argument("--kg", type=float, required=True, help="체중 (kg)")
    p_log.add_argument("--bodyfat", type=float, default=None, metavar="PCT", help="체지방률 (%)")
    p_log.add_argument("--note", default=None, help="메모 (최대 200자)")
    p_log.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="날짜 (기본: 오늘)")

    # trend subcommand
    sub.add_parser("trend", help="체중 추세 요약 (JSON 출력)")

    # summary subcommand
    sub.add_parser("summary", help="코치용 압축 요약 (JSON 출력)")

    # set-target subcommand
    p_tgt = sub.add_parser("set-target", help="목표 체중 설정 (goal.json 병합)")
    p_tgt.add_argument("--kg", type=float, required=True, help="목표 체중 (kg)")

    args = ap.parse_args(argv)
    home = resolve_home(args.home, create=True)

    if args.cmd == "log":
        entry = log_weight(home, args.kg, bodyfat_pct=args.bodyfat, note=args.note, on_date=args.date)
        print(json.dumps(entry, ensure_ascii=False))

    elif args.cmd == "trend":
        result = trend(home)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "summary":
        result = summary(home)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "set-target":
        val = set_target_weight(home, args.kg)
        print(json.dumps({"target_weight_kg": val}, ensure_ascii=False))


if __name__ == "__main__":
    main()
