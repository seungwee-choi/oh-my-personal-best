#!/usr/bin/env python3
"""Weekly review computation for oh-my-personal-best scripts.

Ported from ompb_apps/review.py — weekly-review domain logic only.
Single-session analyze_activity helpers (select_run, latest_strava_run, etc.)
are omitted — they depend on analyze_activity and live in the app layer.

Stdlib only — never imports ompb_core (circular import).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Dict, List, Optional, Tuple

import logquery
import injury
from ompb_env import resolve_home, local_today
from weekplan import week_range, week_plan_path, offset_for_date

# ── constants ─────────────────────────────────────────────────────────────────

_TYPE_KO = {"인터벌": "interval", "템포": "tempo", "롱런": "long", "롱 런": "long",
            "장거리": "long", "회복": "recovery", "이지": "easy", "조깅": "easy"}
_DIST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:km|k|키로|킬로|키미)")

_ZONES = ["Z1", "Z2", "Z3", "Z4", "Z5"]
_CONF = {"high": "높음", "medium": "중", "low": "낮음"}

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DOW_KO = {"Mon": "월", "Tue": "화", "Wed": "수", "Thu": "목",
           "Fri": "금", "Sat": "토", "Sun": "일"}

_KEY_TYPES = {"tempo", "interval", "long"}

_STATUS_KO = {
    "done": "계획대로 수행", "skipped": "건너뜀", "upcoming": "예정(아직 안 함)",
    "cross_only": "러닝 없음(크로스 가능성)",
    "rest_kept": "휴식(계획)", "rest_ran": "휴식일에 뜀", "unplanned": "계획 외 런",
    "skipped_injury": "부상 회복(휴식)", "empty": "기록·계획 없음",
}

_TYPE_KO_LABEL = {
    "easy": "이지", "long": "롱런", "tempo": "템포", "interval": "인터벌",
    "recovery": "회복", "race": "레이스", "cross": "크로스", "rest": "휴식",
}


# ── local goal reader (replaces goalmod.current) ─────────────────────────────

def _current_goal(home: str) -> dict:
    """Read $OMPB_HOME/goal.json; return {} on missing/invalid."""
    path = os.path.join(home, "goal.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


# ── recent-run helpers ────────────────────────────────────────────────────────

def latest_runs(home: Optional[str], n: int = 4) -> List[dict]:
    """The most recent running entries (date-sorted by query_log), newest last."""
    try:
        runs = logquery.query_log(home, sport="running") or []
    except Exception:  # noqa: BLE001
        runs = []
    return runs[-n:] if runs else []


def _fmt(run: dict) -> str:
    """One compact metric line for a run: date · type · dist · pace · HR · cadence · ascent."""
    a = run.get("actual") or {}
    bits = [str(run.get("date") or "?"), run.get("type") or "run",
            f"{a.get('distance_km', '?')}km"]
    if a.get("pace"):
        bits.append(f"{a['pace']}/km")
    if a.get("avg_hr"):
        bits.append(f"HR {a['avg_hr']}" + (f"~{a['max_hr']}" if a.get("max_hr") else ""))
    if a.get("cadence"):
        bits.append(f"케이던스 {a['cadence']}")
    if a.get("ascent_m"):
        bits.append(f"↑{a['ascent_m']}m")
    if a.get("rpe"):
        bits.append(f"RPE {a['rpe']}")
    return " · ".join(bits)


def list_line(run: dict) -> str:
    """One compact run line for the recent-runs picker list."""
    return _fmt(run)


def short_label(run: dict) -> str:
    """A compact one-run label: 'MM/DD 타입 10.1km' (≤ 80 chars)."""
    a = run.get("actual") or {}
    d = str(run.get("date") or "")
    md = d[5:].replace("-", "/") if len(d) >= 10 else (d or "?")
    typ = _TYPE_KO_LABEL.get(run.get("type"), run.get("type") or "런")
    dist = a.get("distance_km")
    label = f"{md} {typ}" + (f" {round(float(dist), 1)}km" if dist else "")
    return label[:80]


def _same_run(a: dict, b: dict) -> bool:
    """date + distance identity (the log's natural key)."""
    aa, bb = a.get("actual") or {}, b.get("actual") or {}
    return a.get("date") == b.get("date") and aa.get("distance_km") == bb.get("distance_km")


def build_prompt_for(home: Optional[str], run: dict, recent: Optional[List[dict]] = None,
                     request: Optional[str] = None, context: Optional[List[str]] = None) -> str:
    """A grounded review prompt for a SPECIFIC run."""
    if recent is None:
        recent = [r for r in latest_runs(home, 5) if not _same_run(r, run)][-3:]
    home_r = resolve_home(home)
    try:
        g = _current_goal(home_r)
    except Exception:  # noqa: BLE001
        g = {}
    a = run.get("actual") or {}
    head = [str(run.get("date") or "?"), f"{a.get('distance_km', '?')}km"]
    if a.get("pace"):
        head.append(f"{a['pace']}/km")
    if a.get("avg_hr"):
        head.append(f"HR {a['avg_hr']}" + (f"~{a['max_hr']}" if a.get("max_hr") else ""))
    if a.get("cadence"):
        head.append(f"케이던스 {a['cadence']}")
    if a.get("ascent_m"):
        head.append(f"↑{a['ascent_m']}m")
    if a.get("rpe"):
        head.append(f"RPE {a['rpe']}")
    lines = ["다음은 러너의 한 달리기야. 이 런을 리뷰해줘 — 짧고 핵심만.",
             "**세션 종류 자동 분류는 무시하고 언급하지 마.** 이 기록은 활동 전체 평균/요약값뿐이라 "
             "랩·구간 분리는 불가능해 — 가진 수치로만 판단해.",
             "[대상 런] " + " · ".join(head)]
    if recent:
        lines.append("[다른 최근 런들] " + " / ".join(_fmt(r) for r in recent))
    if g.get("target_time"):
        lines.append(f"[목표] {g.get('event', '')} {g.get('target_time')} "
                     f"({g.get('target_pace', '')})".strip())
    if context:
        lines += ["[전후 맥락] " + " · ".join(context)]
    if request:
        lines += ["",
                  f"[러너가 밝힌 의도] {request}",
                  "이 의도를 기준으로 평가해 — 의도대로 됐는지. 더는 되묻지 말고 단정적으로. "
                  "단, 의도가 평균값만으론 확인 불가한 것(구간 분리 등)이면 그 한계만 한 줄로 밝히고 "
                  "가능한 분석을 해줘."]
    lines += ["",
              "리뷰 규칙:",
              "- 가진 데이터로 말할 수 있는 것만. **없는 데이터(HR·케이던스 등)는 아예 적지 마 — "
              "'데이터 없음'·'평가 불가' 나열 금지.** 항목을 억지로 채우지 마.",
              "- 형식: ① 한 줄 총평 ② 의미 있는 신호 1~2개 ③ 다음 액션 1~2개. **5~7문장 이내로 짧게.**",
              "- 추측 금지(주어진 수치만). 온보딩 안내(목표 설정·연동) 장황하게 늘어놓지 마."]
    if not request:
        lines.append("- 평균값만으로 세션 의도가 모호하면 단정하지 말고, 추정한 뒤 러너에게 의도를 "
                     "되물어('이건 회복 의도였나요, 가볍게 거리 채우기였나요?') — 아래 입력창에 답하면 "
                     "그 의도로 다시 리뷰한다고 한 줄 안내해.")
    return "\n".join(lines)


def build_prompt(home: Optional[str]) -> Optional[str]:
    """A grounded review prompt for the latest logged run, or None."""
    runs = latest_runs(home)
    if not runs:
        return None
    return build_prompt_for(home, runs[-1], runs[:-1])


# ── weekly calendar: plan ↔ actual overlay ────────────────────────────────────

def day_status(plan_day: Optional[dict], day_runs: List[dict], has_cross: bool = False,
               is_future: bool = False, injured: bool = False) -> str:
    """The one adherence verdict for a single day. Pure — no IO."""
    ran = bool(day_runs)
    planned = bool(plan_day) and (plan_day.get("type") or "") != ""
    is_rest = bool(plan_day) and plan_day.get("type") == "rest"
    if is_rest:
        return "rest_ran" if ran else "rest_kept"
    if planned:
        if ran:
            return "done"
        if has_cross:
            return "cross_only"
        if is_future:
            return "upcoming"
        return "skipped_injury" if injured else "skipped"
    return "unplanned" if ran else "empty"


def run_summary(run: dict) -> dict:
    """Compact, path-free run dict for a calendar cell."""
    sid = str(run.get("source_id") or "")
    return {
        "date": run.get("date"),
        "type": run.get("type"),
        "distance_km": (run.get("actual") or {}).get("distance_km"),
        "label": short_label(run),
        "line": list_line(run),
        "source_id": run.get("source_id"),
        "deep_analyzable": sid.startswith("strava-"),
    }


def _rep_run(day_runs: List[dict]) -> Optional[dict]:
    """The representative run for a day: most recent, ties broken by longest distance."""
    if not day_runs:
        return None
    best = day_runs[0]
    for r in day_runs[1:]:
        if (r.get("date") or "") > (best.get("date") or "") or (
            r.get("date") == best.get("date") and _dist(r) >= _dist(best)
        ):
            best = r
    return best


def _read_plan_days(home: Optional[str], offset: int) -> Tuple[Optional[dict], List[dict]]:
    """Read the plan-week file for ``offset`` via week_plan_path (freshness guard at offset 0).
    Returns (week_meta, days) — (None, []) when no plan file exists."""
    try:
        with open(week_plan_path(home, offset), encoding="utf-8") as fh:
            plan = json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return None, []
    if not isinstance(plan, dict):
        return None, []
    days = plan.get("days") if isinstance(plan.get("days"), list) else []
    week_meta = plan.get("week") if isinstance(plan.get("week"), dict) else None
    notes = plan.get("coach_notes")
    if week_meta is not None and isinstance(notes, list) and notes:
        week_meta = {**week_meta, "coach_notes": notes}
    return week_meta, days


def week_overview(home: Optional[str], offset: int = 0) -> dict:
    """Combine one week's plan + actual runs into 7 day cells with adherence verdict each."""
    start, end = week_range(offset)
    week_meta, plan_days = _read_plan_days(home, offset)
    has_plan = bool(plan_days)

    try:
        runs = logquery.query_log(home, since=start, until=end, sport="running") or []
    except Exception:  # noqa: BLE001
        runs = []
    try:
        all_entries = logquery.query_log(home, since=start, until=end) or []
    except Exception:  # noqa: BLE001
        all_entries = []

    runs_by_date: dict = {}
    for r in runs:
        runs_by_date.setdefault(r.get("date"), []).append(r)
    cross_dates = {e.get("date") for e in all_entries if e.get("sport") != "running"}

    plan_by_date = {d.get("date"): d for d in plan_days if isinstance(d, dict)}
    today = local_today().isoformat()
    inj_dates = injury.injured_dates(home, start, end)

    days = []
    for i in range(7):
        date = (_dt.date.fromisoformat(start) + _dt.timedelta(days=i)).isoformat()
        plan_day = plan_by_date.get(date)
        day_runs = runs_by_date.get(date, [])
        has_cross = (not day_runs) and (date in cross_dates)
        status = day_status(plan_day, day_runs, has_cross, is_future=(date >= today),
                            injured=(date in inj_dates))
        rep = _rep_run(day_runs)
        plan_vs_actual = None
        if plan_day is not None:
            plan_vs_actual = {
                "planned_km": plan_day.get("distance_km") or 0,
                "actual_km": round(sum(_dist(r) for r in day_runs), 2),
            }
        plan_view = None
        if plan_day is not None:
            plan_view = {
                "type": plan_day.get("type"), "distance_km": plan_day.get("distance_km"),
                "pace": plan_day.get("pace"), "title": plan_day.get("title"),
                "structure": plan_day.get("structure"), "purpose": plan_day.get("purpose"),
                "hr_zone": plan_day.get("hr_zone"),
            }
        days.append({
            "date": date,
            "dow": _DOW[i],
            "plan": plan_view,
            "runs": [run_summary(r) for r in day_runs],
            "rep_run": run_summary(rep) if rep else None,
            "extra_count": max(0, len(day_runs) - 1),
            "status": status,
            "plan_vs_actual": plan_vs_actual,
            "has_cross": has_cross,
        })

    meta = None
    if week_meta:
        meta = {
            "phase": week_meta.get("phase"), "focus": week_meta.get("focus"),
            "target_km": week_meta.get("target_km"), "ramp_pct": week_meta.get("ramp_pct"),
            "prev_week_km": week_meta.get("prev_week_km"),
            "coach_notes": week_meta.get("coach_notes"),
        }
    return {"offset": offset, "start": start, "end": end, "has_plan": has_plan,
            "week_meta": meta, "days": days}


def context_for(home: Optional[str], run: dict) -> dict:
    """Before/after context for ONE run, attributed to the week it actually falls in."""
    date = run.get("date") or ""
    out: dict = {}

    # (a) that day's plan vs actual
    try:
        off = offset_for_date(date)
    except Exception:  # noqa: BLE001
        off = None
    plan_day = None
    if off is not None:
        _meta, plan_days = _read_plan_days(home, off)
        plan_day = next((d for d in plan_days if isinstance(d, dict) and d.get("date") == date),
                        None)
    if plan_day is not None:
        actual_km = round(_dist(run), 2)
        plan_axis: dict = {
            "has_plan": True, "type": plan_day.get("type"),
            "title": plan_day.get("title"), "planned_km": plan_day.get("distance_km") or 0,
            "actual_km": actual_km,
            "status": day_status(plan_day, [run], has_cross=False),
        }
    else:
        plan_axis = {"has_plan": False, "note": "그날 계획 기록 없음"}
    out["plan_vs_actual"] = plan_axis

    # (b) same-week prior/next running sessions
    prev_run = next_run = None
    if off is not None:
        try:
            wk_start, wk_end = week_range(off)
            week_runs = logquery.query_log(home, since=wk_start, until=wk_end,
                                           sport="running") or []
        except Exception:  # noqa: BLE001
            week_runs = []
        idx = next((i for i, r in enumerate(week_runs) if _same_run(r, run)), None)
        if idx is not None:
            if idx > 0:
                prev_run = week_runs[idx - 1]
            if idx < len(week_runs) - 1:
                next_run = week_runs[idx + 1]
    out["adjacent"] = {"prev": _fmt(prev_run) if prev_run else None,
                       "next": _fmt(next_run) if next_run else None}

    # (c) weekly-load position
    load: dict = {}
    _meta_c, _ = _read_plan_days(home, off) if off is not None else (None, [])
    if _meta_c and (_meta_c.get("target_km") or _meta_c.get("ramp_pct")):
        load = {"source": "plan", "target_km": _meta_c.get("target_km"),
                "ramp_pct": _meta_c.get("ramp_pct"), "prev_week_km": _meta_c.get("prev_week_km")}
    else:
        try:
            y, w, _wd = _dt.date.fromisoformat(date).isocalendar()
            key = f"{y}-W{w:02d}"
            rows = logquery.weekly_load(home) or []
            row = next((r for r in rows if r.get("week") == key), None)
            if row is not None:
                load = {"source": "weekly_load", "distance_km": row.get("distance_km"),
                        "sessions_advisory": row.get("sessions")}
        except Exception:  # noqa: BLE001
            load = {}
    out["weekly_load"] = load

    # (d) goal
    home_r = resolve_home(home)
    try:
        out["goal"] = _current_goal(home_r)
    except Exception:  # noqa: BLE001
        out["goal"] = {}

    # (e) injury
    try:
        out["injury"] = injury.snapshot(home)
    except Exception:  # noqa: BLE001
        out["injury"] = {"active": False}
    return out


def render_context_lines(ctx: dict) -> list:
    """Render ``context_for`` dict → Korean prompt lines. Pure — no IO."""
    lines: list = []
    inj = ctx.get("injury") or {}
    if inj.get("active"):
        ep = inj.get("primary") or {}
        phase_label = injury.phase_meta(ep.get("phase", "easy_only"))["label"]
        lines.append(
            f"부상 회복 중: {ep.get('label', '부상')} · {phase_label} 단계 · 부하 상한 "
            f"{inj.get('load_cap_pct')}% — 느린 페이스/짧은 거리/중단은 이 맥락에서 해석하세요")
    pa = ctx.get("plan_vs_actual") or {}
    if pa.get("has_plan"):
        ko = _STATUS_KO.get(pa.get("status"), pa.get("status") or "")
        typ = pa.get("type") or "런"
        title = f" '{pa['title']}'" if pa.get("title") else ""
        lines.append(f"그날 계획 대비: 계획 {typ}{title} {pa.get('planned_km', 0)}km → "
                     f"실제 {pa.get('actual_km', 0)}km ({ko})")
    else:
        lines.append("그날 계획 대비: 그날 계획 기록 없음 (계획 외 런)")

    adj = ctx.get("adjacent") or {}
    if adj.get("prev"):
        lines.append("같은 주 직전 세션: " + adj["prev"])
    if adj.get("next"):
        lines.append("같은 주 직후 세션: " + adj["next"])

    load = ctx.get("weekly_load") or {}
    if load.get("source") == "plan":
        bits = []
        if load.get("target_km") is not None:
            bits.append(f"목표 {load['target_km']}km")
        if load.get("ramp_pct") is not None:
            bits.append(f"증감 {load['ramp_pct']}%")
        if load.get("prev_week_km") is not None:
            bits.append(f"전주 {load['prev_week_km']}km")
        if bits:
            lines.append("주간 부하(계획): " + " · ".join(bits))
    elif load.get("source") == "weekly_load":
        sess = load.get("sessions_advisory")
        sess_txt = f" · 세션 {sess}회(크로스 포함, 참고)" if sess is not None else ""
        lines.append(f"주간 부하(실측): 그 주 누적 {load.get('distance_km')}km{sess_txt}")

    g = ctx.get("goal") or {}
    if g.get("target_time"):
        lines.append(f"목표: {g.get('event', '')} {g.get('target_time')} "
                     f"({g.get('target_pace', '')})".strip())
    return lines


# ── weekly training review ────────────────────────────────────────────────────

def _planned_training_days(days: List[dict]) -> List[dict]:
    """The week's non-rest planned day cells (Mon→Sun order) from week_overview days."""
    return [d for d in days
            if (d.get("plan") or {}).get("type") not in (None, "", "rest")]


def week_review_status(home: Optional[str], offset: int = 0) -> dict:
    """Is this week's training effectively complete — ready to surface the weekly review?

    ``ready`` = plan exists with ≥1 non-rest day, last planned training day is today-or-past
    AND done, no past-or-today planned session is still upcoming, ≥1 run logged this week."""
    ov = week_overview(home, offset)
    days = ov.get("days") or []
    today = local_today().isoformat()
    planned = _planned_training_days(days)
    runs_count = sum(len(d.get("runs") or []) for d in days)
    out = {
        "offset": offset, "start": ov.get("start"), "end": ov.get("end"),
        "has_plan": ov.get("has_plan", False), "planned_sessions": len(planned),
        "completed_sessions": sum(1 for d in planned if d.get("status") == "done"),
        "runs_count": runs_count, "ready": False,
    }
    if not planned:
        return out
    last = planned[-1]
    pending_due = any(d.get("status") == "upcoming" and (d.get("date") or "") <= today
                      for d in planned)
    out["last_training_date"] = last.get("date")
    out["last_training_dow"] = last.get("dow")
    out["ready"] = bool(
        (last.get("date") or "") <= today
        and last.get("status") == "done"
        and not pending_due
        and runs_count >= 1
    )
    return out


def _day_brief(d: dict) -> Optional[str]:
    """One compact Korean line for a day cell (plan vs actual + verdict). None for empty days."""
    plan = d.get("plan") or {}
    runs = d.get("runs") or []
    if not plan and not runs:
        return None
    dow = _DOW_KO.get(d.get("dow"), d.get("dow") or "")
    ko = _STATUS_KO.get(d.get("status"), d.get("status") or "")
    if (plan.get("type") or "") not in ("", None):
        ptype = _TYPE_KO_LABEL.get(plan.get("type"), plan.get("type"))
        pkm = plan.get("distance_km")
        plan_txt = f"계획 {ptype}" + (f" {pkm}km" if pkm else "")
    else:
        plan_txt = "계획 없음"
    akm = round(sum((r.get("distance_km") or 0) for r in runs), 1)
    act_txt = f"{akm}km" if runs else "기록 없음"
    return f"{dow}: {plan_txt} → 실제 {act_txt} ({ko})"


def week_review_aggregate(home: Optional[str], offset: int = 0) -> dict:
    """Deterministic weekly roll-up: plan↔actual volume, adherence, key-session execution,
    weekly target/ramp, goal, injury, and per-day brief lines. Pure — no LLM/network."""
    ov = week_overview(home, offset)
    days = ov.get("days") or []
    meta = ov.get("week_meta") or {}
    planned = _planned_training_days(days)
    completed = [d for d in planned if d.get("status") == "done"]
    skipped = [d for d in planned if d.get("status") in ("skipped", "skipped_injury")]
    key_planned = [d for d in planned if (d.get("plan") or {}).get("type") in _KEY_TYPES]
    key_done = [d for d in key_planned if d.get("status") == "done"]
    planned_km = round(sum((d.get("plan") or {}).get("distance_km") or 0 for d in planned), 1)
    actual_km = round(
        sum(sum((r.get("distance_km") or 0) for r in (d.get("runs") or [])) for d in days), 1)
    runs_count = sum(len(d.get("runs") or []) for d in days)
    adherence_pct = round(len(completed) / len(planned) * 100) if planned else None
    brief = [b for b in (_day_brief(d) for d in days) if b]

    home_r = resolve_home(home)
    try:
        goal = _current_goal(home_r)
    except Exception:  # noqa: BLE001
        goal = {}
    try:
        inj = injury.snapshot(home)
    except Exception:  # noqa: BLE001
        inj = {"active": False}

    return {
        "offset": offset, "start": ov.get("start"), "end": ov.get("end"),
        "has_plan": ov.get("has_plan", False),
        "phase": meta.get("phase"), "focus": meta.get("focus"),
        "target_km": meta.get("target_km"), "ramp_pct": meta.get("ramp_pct"),
        "prev_week_km": meta.get("prev_week_km"), "coach_notes": meta.get("coach_notes"),
        "planned_sessions": len(planned), "completed_sessions": len(completed),
        "skipped_sessions": len(skipped),
        "key_planned": len(key_planned), "key_done": len(key_done),
        "planned_km": planned_km, "actual_km": actual_km, "runs_count": runs_count,
        "adherence_pct": adherence_pct, "days_brief": brief,
        "goal": goal, "injury": inj,
        "metrics": {
            "adherence_pct": adherence_pct, "planned_km": planned_km,
            "actual_km": actual_km, "completed_sessions": len(completed),
            "planned_sessions": len(planned), "key_done": len(key_done),
            "key_planned": len(key_planned), "runs_count": runs_count,
        },
    }


def format_week_summary(agg: dict) -> str:
    """Deterministic '한 주 훈련 리뷰' card from the aggregate (no LLM)."""
    lines = [f"📅 **한 주 훈련 리뷰** — {agg.get('start')} ~ {agg.get('end')}", ""]
    ps, cs = agg.get("planned_sessions") or 0, agg.get("completed_sessions") or 0
    if ps:
        adh = agg.get("adherence_pct")
        key = (f" · 핵심 {agg.get('key_done', 0)}/{agg['key_planned']}"
               if agg.get("key_planned") else "")
        lines.append(f"• 이행: {cs}/{ps} 세션" + (f" ({adh}%)" if adh is not None else "") + key)
    pkm, akm = agg.get("planned_km") or 0, agg.get("actual_km") or 0
    vol = f"• 볼륨: 계획 {pkm}km → 실제 {akm}km"
    if agg.get("target_km"):
        vol += f" (목표 {agg['target_km']}km)"
    lines.append(vol)
    if agg.get("phase") or agg.get("focus"):
        lines.append("• 페이즈: " + " · ".join(
            x for x in (agg.get("phase"), agg.get("focus")) if x))
    return "\n".join(lines)


def week_review_prompt(home: Optional[str], agg: dict) -> str:
    """A grounded weekly-review prompt for the coach: read the WEEK as a whole, give ONE
    concrete next-week direction. Short, goal-aware, injury-aware."""
    g = agg.get("goal") or {}
    inj = agg.get("injury") or {}
    lines = [
        "다음은 러너의 '한 주' 훈련 요약이야. 이 한 주를 통째로 리뷰해줘 — 하루 단위가 아니라 주 단위 흐름으로.",
        f"[주간] {agg.get('start')} ~ {agg.get('end')}",
        f"[이행] 계획 {agg.get('planned_sessions', 0)}세션 중 {agg.get('completed_sessions', 0)} 완료"
        + (f" ({agg['adherence_pct']}%)" if agg.get("adherence_pct") is not None else "")
        + (f", 핵심 세션 {agg.get('key_done', 0)}/{agg.get('key_planned', 0)}"
           if agg.get("key_planned") else ""),
        f"[볼륨] 계획 {agg.get('planned_km', 0)}km → 실제 {agg.get('actual_km', 0)}km"
        + (f" (주간 목표 {agg['target_km']}km)" if agg.get("target_km") else "")
        + (f", 증감 {agg['ramp_pct']}%" if agg.get("ramp_pct") is not None else ""),
    ]
    if agg.get("phase") or agg.get("focus"):
        lines.append("[페이즈/포커스] " + " · ".join(
            x for x in (agg.get("phase"), agg.get("focus")) if x))
    if agg.get("days_brief"):
        lines.append("[요일별] " + " / ".join(agg["days_brief"]))
    if g.get("target_time"):
        lines.append(f"[목표] {g.get('event', '')} {g.get('target_time')} "
                     f"({g.get('target_pace', '')})".strip())
    if inj.get("active"):
        ep = inj.get("primary") or {}
        lines.append(f"[부상] {ep.get('label', '부상')} 회복 중 — 미수행/저강도는 회복 맥락으로 해석")
    lines += [
        "",
        "리뷰 규칙:",
        "- 주 단위 흐름으로: 계획 대비 이행·볼륨, 핵심 세션 수행, 일관성(요일 분포)을 읽어.",
        "- 형식: ① 이번 주 한 줄 총평 ② 잘된 점 1~2개 ③ 아쉬운 점/리스크 1~2개 ④ 다음 주 방향 한 줄"
        "(원칙·강조점). **8문장 이내로 짧게.**",
        "- 이건 '지난 한 주 회고'야. **특정 세션을 처방하지 마** — '오늘/내일 …를 뛰어라', 구체적 "
        "거리·페이스·요일 지정 금지. 그건 주간 계획의 몫이야.",
        "- **계획·데이터에 없는 수치(페이스·거리·심박)를 절대 지어내지 마.** 가진 수치로만, 추측 금지, "
        "마크다운 기호 쓰지 마.",
        "- '다음 주 방향'은 처방이 아니라 원칙/강조점이어야 해(예: '이지 비중을 유지하며 롱런을 점진적으로', "
        "'핵심 세션을 주 초반에 배치'). 날짜·거리·페이스를 박지 마.",
        "- 아직 안 끝난 세션이 있어도 '가서 뛰어라'라고 시키지 마 — 중립적으로만 언급해.",
        "- 미수행이 있어도 비난조 금지 — 코치답게 따뜻한 톤으로.",
    ]
    return "\n".join(lines)


def _dist(run: dict) -> float:
    return (run.get("actual") or {}).get("distance_km") or 0.0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        description="Weekly review computation CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Subcommands: overview, status, aggregate",
    )
    ap.add_argument("--home", help="Explicit OMPB_HOME override.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ov = sub.add_parser("overview", help="Print week_overview JSON.")
    p_ov.add_argument("--offset", type=int, default=0)

    p_st = sub.add_parser("status", help="Print week_review_status JSON.")
    p_st.add_argument("--offset", type=int, default=0)

    p_ag = sub.add_parser("aggregate", help="Print week_review_aggregate JSON.")
    p_ag.add_argument("--offset", type=int, default=0)

    a = ap.parse_args(argv)
    home = resolve_home(a.home)

    if a.cmd == "overview":
        out = week_overview(home, a.offset)
    elif a.cmd == "status":
        out = week_review_status(home, a.offset)
    elif a.cmd == "aggregate":
        out = week_review_aggregate(home, a.offset)
    else:  # pragma: no cover
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
