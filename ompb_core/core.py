"""Facade implementation. See package docstring for the contract.

Read paths (state/query/aggregation/report-data) import the script helpers
in-process. Write/render paths (import/sync/render) shell out to the scripts so
their argv parsing, dedup, integrity guards, and stderr summaries stay authoritative.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# The deterministic toolkit lives in <repo>/scripts. Put it on the path so we can
# import its pure helpers, and locate it for subprocess calls.
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ompb_env  # noqa: E402  (resolved via SCRIPTS on sys.path)
import build_report as _report  # noqa: E402


class OMPBError(RuntimeError):
    """A toolkit operation failed (bad input, script non-zero exit, etc.)."""


# --------------------------------------------------------------------------- #
# Home / language
# --------------------------------------------------------------------------- #

def resolve_home(home: Optional[str] = None, create: bool = False) -> str:
    """Absolute OMPB_HOME via the documented precedence ($OMPB_HOME -> ~/.ompb -> ./.ompb)."""
    return ompb_env.resolve_home(home, create=create)


def resolve_lang(lang: Optional[str] = None, home: Optional[str] = None) -> str:
    """Output language: explicit -> config.json `language` -> 'en'."""
    return ompb_env.resolve_lang(lang, resolve_home(home))


# --------------------------------------------------------------------------- #
# Read paths (in-process)
# --------------------------------------------------------------------------- #

def _read_state(home: str, filename: str) -> Optional[Any]:
    path = ompb_env.state_path(home, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _load_log(home: str) -> List[Dict]:
    path = ompb_env.log_path(home)
    if not os.path.exists(path):
        return []
    return _report.load_log(path)


def get_state(home: Optional[str] = None) -> Dict[str, Any]:
    """A snapshot of the runner's state: profile, goal, plan, config, and log stats."""
    home = resolve_home(home)
    log = _load_log(home)
    dates = sorted(e["date"] for e in log if e.get("date"))
    return {
        "home": home,
        "profile": _read_state(home, "runner-profile.json"),
        "goal": _read_state(home, "goal.json"),
        "plan_state": _read_state(home, "plan-state.json"),
        "config": ompb_env.read_config(home),
        "log_count": len(log),
        "earliest_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
    }


def query_log(
    home: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    sport: Optional[str] = None,
    type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    """Filtered, date-sorted training-log entries. Dates are 'YYYY-MM-DD' strings."""
    home = resolve_home(home)
    out: List[Dict] = []
    for e in _load_log(home):
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
    for e in _load_log(home):
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
    rows = [{"week": v["week"], "distance_km": round(v["distance_km"], 1), "sessions": v["sessions"]}
            for _, v in sorted(buckets.items())]
    return rows[-int(weeks):] if weeks else rows


def report_data(home: Optional[str] = None) -> Dict[str, Any]:
    """The structured REPORT_DATA object (athlete/totals/pbs/monthly/hr/diagnosis/…)
    that the HTML report is rendered from — useful for programmatic consumers."""
    home = resolve_home(home)
    try:
        return _report.build_report_data(home)
    except SystemExit as e:  # build_report raises SystemExit on an empty log
        raise OMPBError(str(e))


# --------------------------------------------------------------------------- #
# Write / render paths (subprocess — faithful to the CLI contract)
# --------------------------------------------------------------------------- #

def _run(script: str, args: List[str], home: Optional[str]) -> subprocess.CompletedProcess:
    home = resolve_home(home, create=True)
    cmd = [sys.executable, str(SCRIPTS / script), *args, "--home", home]
    env = dict(os.environ, OMPB_NO_CTA="1")  # suppress the interactive star CTA
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise OMPBError((proc.stderr or proc.stdout or f"{script} failed").strip())
    return proc


def import_file(
    path: str,
    home: Optional[str] = None,
    tz: Optional[str] = None,
    long_threshold: Optional[float] = None,
) -> str:
    """Import a .fit / .zip / directory (Garmin/COROS) or a .csv (Strava-style) into
    the training log. Returns the importer's summary (new / duplicates / by sport)."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise OMPBError(f"file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        proc = _run("import_csv.py", [path], home)
    elif ext in (".fit", ".zip") or os.path.isdir(path):
        args = [path]
        if tz:
            args += ["--tz", tz]
        if long_threshold is not None:
            args += ["--long-threshold", str(long_threshold)]
        proc = _run("import_fit.py", args, home)
    else:
        raise OMPBError(f"unsupported input: {ext or path} (use .fit/.zip/.csv or a directory)")
    return (proc.stderr or proc.stdout or "import complete").strip()


def sync_strava(
    home: Optional[str] = None,
    after: Optional[str] = None,
    max_pages: Optional[int] = None,
    access_token: Optional[str] = None,
) -> str:
    """Sync Strava activities (auto-refreshing the stored token) into the log.
    Requires a prior connect (strava.json) unless a one-shot access_token is given."""
    args: List[str] = []
    if after:
        args += ["--after", after]
    if max_pages is not None:
        args += ["--max-pages", str(max_pages)]
    if access_token:
        args += ["--access-token", access_token]
    proc = _run("import_strava.py", args, home)
    return (proc.stderr or "sync complete").strip()


def build_report(home: Optional[str] = None, lang: Optional[str] = None,
                 out: Optional[str] = None) -> str:
    """Render the comprehensive self-contained HTML analysis report. Returns the file path."""
    args: List[str] = []
    if lang:
        args += ["--lang", lang]
    if out:
        args += ["--out", out]
    proc = _run("build_report.py", args, home)
    return (proc.stdout or "").strip().splitlines()[-1]


def build_week(home: Optional[str] = None, lang: Optional[str] = None,
               plan: Optional[str] = None, out: Optional[str] = None) -> str:
    """Render this week's plan card (from plan-week.json). Returns the file path."""
    args: List[str] = []
    if lang:
        args += ["--lang", lang]
    if plan:
        args += ["--plan", plan]
    if out:
        args += ["--out", out]
    proc = _run("build_week.py", args, home)
    return (proc.stdout or "").strip().splitlines()[-1]
