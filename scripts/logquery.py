#!/usr/bin/env python3
"""Shared log-reading helpers for oh-my-personal-best scripts.

Reads $OMPB_HOME/training-log.jsonl (one JSON object per line).
Stdlib only — never imports ompb_core (circular import).
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Dict, List, Optional

from ompb_env import resolve_home, log_path


def load_log(home: str) -> List[Dict]:
    """Load the training log; skip blank/bad lines."""
    path = log_path(home)
    rows: List[Dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except (ValueError, json.JSONDecodeError):
                    pass
    except (FileNotFoundError, OSError):
        pass
    return rows


def query_log(
    home: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    sport: Optional[str] = None,
    type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    """Filtered, date-sorted training-log entries. Dates are 'YYYY-MM-DD' strings.
    ``limit`` keeps the LAST n entries after sorting."""
    home = resolve_home(home)
    out: List[Dict] = []
    for e in load_log(home):
        d = e.get("date")
        if since and (not d or d < since):
            continue
        if until and (not d or d > until):
            continue
        if sport and e.get("sport") != sport:
            continue
        if type and e.get("type") != type:
            continue
        out.append(e)
    out.sort(key=lambda e: e.get("date") or "")
    if limit:
        out = out[-int(limit):]
    return out


def weekly_load(home: Optional[str] = None, weeks: int = 12) -> List[Dict]:
    """Per-ISO-week distance + session count, oldest→newest, last ``weeks`` weeks."""
    home = resolve_home(home)
    buckets: Dict[str, Dict] = {}
    for e in load_log(home):
        d = e.get("date")
        if not d:
            continue
        try:
            y, w, _ = _dt.date.fromisoformat(d).isocalendar()
        except ValueError:
            continue
        key = f"{y}-W{w:02d}"
        b = buckets.setdefault(key, {"week": key, "distance_km": 0.0, "sessions": 0})
        actual = e.get("actual") or {}
        b["distance_km"] += actual.get("distance_km") or 0
        b["sessions"] += 1
    rows = [
        {"week": v["week"], "distance_km": round(v["distance_km"], 1), "sessions": v["sessions"]}
        for _, v in sorted(buckets.items())
    ]
    return rows[-int(weeks):] if weeks else rows


def is_run(r: dict) -> bool:
    """A running activity: sport in (None, 'running') and type != 'cross'.

    Strava imports tag sport='running'; CSV imports omit sport entirely —
    treat a missing sport as a run unless it's typed cross.
    """
    if r.get("sport") not in (None, "running"):
        return False
    return r.get("type") != "cross"


def pace_sec(pace) -> Optional[int]:
    """Seconds from 'M:SS' pace string, or None."""
    if not pace or ":" not in str(pace):
        return None
    try:
        mm, ss = str(pace).split(":")[:2]
        return int(mm) * 60 + int(ss)
    except ValueError:
        return None
