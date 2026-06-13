#!/usr/bin/env python3
"""Week boundaries + plan-week file lifecycle for oh-my-personal-best scripts.

Ported from ompb_apps/analysis.py — week-boundary and plan-file helpers only.
Stdlib only — never imports ompb_core (circular import).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Optional, Tuple

from ompb_env import resolve_home, local_today

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── week boundary helpers ─────────────────────────────────────────────────────

def _week_monday(offset: int = 0) -> _dt.date:
    """Monday of (this week + ``offset`` weeks) in KST."""
    today = local_today()
    return today - _dt.timedelta(days=today.weekday()) + _dt.timedelta(days=7 * offset)


def _week_days(offset: int = 0) -> list:
    """Mon–Sun of (this week + ``offset`` weeks) as ``{date, dow}`` scaffold."""
    monday = _week_monday(offset)
    return [{"date": (monday + _dt.timedelta(days=i)).isoformat(), "dow": _DOW[i]}
            for i in range(7)]


def week_range(offset: int = 0) -> Tuple[str, str]:
    """(start_iso, end_iso) Mon..Sun of the week at ``offset``."""
    days = _week_days(offset)
    return days[0]["date"], days[-1]["date"]


def offset_for_date(date_iso: str) -> int:
    """Week offset (relative to this week) for ``date_iso``: past < 0, this = 0, future > 0.
    Computed Mon–Sun: (that date's Monday − this Monday) / 7."""
    d = _dt.date.fromisoformat(date_iso)
    that_monday = d - _dt.timedelta(days=d.weekday())
    return (that_monday - _week_monday(0)).days // 7


def week_plan_path(home: Optional[str], offset: int = 0) -> str:
    """Plan file for the week at ``offset``:
    offset 0 → ``plan-week.json`` (legacy live slot, runs freshness guard);
    any other offset → ``plan-week-<that-Monday>.json``."""
    home = resolve_home(home)
    if offset == 0:
        archive_if_stale(home)
        return os.path.join(home, "plan-week.json")
    return os.path.join(home, f"plan-week-{_week_monday(offset).isoformat()}.json")


def _plan_week_monday(plan: dict) -> Optional[_dt.date]:
    """The Monday of the week the plan belongs to (from week.start_date or first day's date).
    None when neither is present/parseable — caller treats as 'this week' (safe no-op)."""
    src = (
        ((plan.get("week") or {}).get("start_date"))
        or (((plan.get("days") or [{}])[0] or {}).get("date"))
    )
    if not src:
        return None
    try:
        d = _dt.date.fromisoformat(str(src))
    except (ValueError, TypeError):
        return None
    return d - _dt.timedelta(days=d.weekday())


def _write(path: str, obj: dict) -> None:
    """Atomic JSON write: temp-file + os.replace."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def archive_if_stale(home: Optional[str]) -> bool:
    """Idempotent week-rollover guard for the offset-0 ``plan-week.json``.

    1. Archive a stale (past-week) current plan to ``plan-week-<Monday>.json``,
       copy-verify-delete so a crash never loses data.
    2. Promote a pre-made this-week plan (``plan-week-<this-Monday>.json``) into the
       live slot when there is no fresh current plan.

    Returns True iff it changed anything. Never raises — it runs inside read chokepoints.
    """
    home = resolve_home(home)
    path = os.path.join(home, "plan-week.json")
    this_monday = _week_monday(0)
    changed = False
    try:
        # ── 1) archive a stale (rolled-over) current plan ────────────────────────────
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                plan = json.load(fh) or {}
            if not isinstance(plan, dict) or not plan.get("days"):
                return False  # blank/invalid current → leave it
            monday = _plan_week_monday(plan)
            if monday is None:
                return False  # unparseable date → treat as fresh, no-op
            if monday == this_monday:
                return False  # already this week → fresh, nothing to do
            dst = os.path.join(home, f"plan-week-{monday.isoformat()}.json")
            if not os.path.isfile(dst):
                _write(dst, plan)  # ① write archive (never overwrite existing)
            with open(dst, encoding="utf-8") as fh:  # ② verify
                if not (json.load(fh) or {}).get("days"):
                    return False  # archive missing/corrupt → keep source (no data loss)
            os.remove(path)  # ③ archive verified → drop stale source
            changed = True
        # ── 2) promote a pre-made this-week plan into the now-empty live slot ─────────
        if not os.path.isfile(path):
            src = os.path.join(home, f"plan-week-{this_monday.isoformat()}.json")
            if os.path.isfile(src):
                with open(src, encoding="utf-8") as fh:
                    p = json.load(fh) or {}
                if isinstance(p, dict) and p.get("days"):
                    _write(path, p)
                    changed = True
        return changed
    except Exception:  # noqa: BLE001 — read chokepoint must never raise
        return False
