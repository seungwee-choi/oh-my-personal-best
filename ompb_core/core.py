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

# The deterministic toolkit (scripts/ + templates/) lives at the repo root for the
# Claude Code plugin, and is also copied into ompb_core/_bundled/ at build time
# (see setup.py) so an installed wheel is self-contained. Resolve whichever exists —
# repo root first, so a dev's edits to scripts/ are picked up over a stale bundle.
def _toolkit_scripts() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "scripts",        # repo root (editable / source checkout)
                 here / "_bundled" / "scripts"):  # bundled into the wheel
        if cand.is_dir():
            return cand
    return here.parent / "scripts"  # default; a clear ImportError follows if truly absent


SCRIPTS = _toolkit_scripts()
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Build scripts locate templates relative to their own file (../templates), so the
# bundled copy keeps scripts/ and templates/ as siblings under _bundled/ — no extra wiring.
import ompb_env  # noqa: E402  (resolved via SCRIPTS on sys.path)
import build_report as _report  # noqa: E402
# Promoted domain modules (stdlib, self-locking atomic state). Imported in-process — they
# read/write small JSON state files (injuries.jsonl, body.jsonl, config.json, goal.json) with
# their own integrity guards, so unlike the importer/render pipeline they don't need the
# subprocess isolation. None of them import ompb_core (that would be circular).
import logquery as _logquery  # noqa: E402  (single source for log read/query/weekly-load)
import injury as _injury  # noqa: E402
import body as _body  # noqa: E402
import zones as _zones  # noqa: E402
import weather as _weather  # noqa: E402
import review as _review  # noqa: E402
# insights (the detector pipeline) is imported lazily in detect_insights — it pulls a larger
# detector package and is only needed on demand.


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
    """Filtered, date-sorted training-log entries. Dates are 'YYYY-MM-DD' strings.
    Delegates to scripts/logquery.py so this and the promoted domain modules (review/insights)
    share ONE log-query implementation — no drift between the facade and the toolkit."""
    return _logquery.query_log(resolve_home(home), since=since, until=until,
                               sport=sport, type=type, limit=limit)


def weekly_load(home: Optional[str] = None, weeks: int = 12) -> List[Dict]:
    """Per-ISO-week distance + session count, oldest→newest, last ``weeks`` weeks.
    Delegates to scripts/logquery.py (single source — see ``query_log``)."""
    return _logquery.weekly_load(resolve_home(home), weeks=weeks)


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


def build_activity(source: str, home: Optional[str] = None, lang: Optional[str] = None,
                   out: Optional[str] = None, long_threshold: Optional[float] = None) -> str:
    """Render a single-activity analysis CARD (laps + streams → structure/reps/pacing/
    decoupling/zones/GAP) to a self-contained HTML file. ``source`` = .fit path or
    "strava-<id>"/"<id>". Returns the output path. Single-activity only — never bulk."""
    s = str(source)
    args = (["--strava", s] if (s.startswith("strava-") or s.isdigit()) else ["--fit", s])
    if lang:
        args += ["--lang", lang]
    if out:
        args += ["--out", out]
    if long_threshold is not None:
        args += ["--long-threshold", str(long_threshold)]
    proc = _run("build_activity.py", args, home)
    return (proc.stdout or "").strip().splitlines()[-1]


def reclassify(home: Optional[str] = None, long_threshold: Optional[float] = None,
               dry_run: bool = False) -> str:
    """Re-type running sessions with the calibrated, runner-relative classifier
    (recovery/easy/tempo/interval/long). Idempotent; run after an import to refine the
    coarse easy/long device labels. Returns the summary (counts before/after)."""
    args: List[str] = []
    if long_threshold is not None:
        args += ["--long-threshold", str(long_threshold)]
    if dry_run:
        args += ["--dry-run"]
    proc = _run("reclassify.py", args, home)
    return (proc.stderr or "reclassified").strip()


def analyze_activity(source: str, home: Optional[str] = None,
                     long_threshold: Optional[float] = None, write: bool = False) -> Dict[str, Any]:
    """Deep-analyze ONE activity from its laps + per-second streams: workout structure
    (interval reps / tempo / progression / steady), pacing, aerobic decoupling, time-in-zone,
    hard-effort count, and grade-adjusted pace. ``source`` is a .fit path (offline) or a Strava
    activity id / "strava-<id>" (≤2 API calls; needs strava.json). ``write=True`` locks the
    matched log entry to the analyzed type (type_source='laps'). Single-activity only — never bulk."""
    s = str(source)
    args = (["--strava", s] if (s.startswith("strava-") or s.isdigit()) else ["--fit", s])
    if long_threshold is not None:
        args += ["--long-threshold", str(long_threshold)]
    if write:
        args.append("--write")
    proc = _run("analyze_activity.py", args, home)
    return json.loads(proc.stdout)


def export_report(home: Optional[str] = None, fmt: str = "pdf", lang: Optional[str] = None,
                  out: Optional[str] = None, html: Optional[str] = None) -> str:
    """Render the analysis report to a static artifact (``fmt`` = "pdf" | "png") via a
    headless browser. Returns the output path. Raises OMPBError if no browser is found.
    Lets surfaces deliver a clean file without re-implementing browser plumbing."""
    args: List[str] = ["--fmt", fmt]
    if lang:
        args += ["--lang", lang]
    if out:
        args += ["--out", out]
    if html:
        args += ["--html", html]
    proc = _run("export_report.py", args, home)
    return (proc.stdout or "").strip().splitlines()[-1]


# --------------------------------------------------------------------------- #
# Domain state — injury / body / zones / weather (in-process, atomic state)
# --------------------------------------------------------------------------- #
# Surface-agnostic coaching domains promoted from the end-user surfaces so every
# consumer (this plugin, the MCP server, the Agent SDK app) shares one source of
# truth. The deterministic state/compute lives in scripts/<domain>.py; the LLM
# narrative (the actual coaching voice) stays in the agents/prompts.

# ── Injury tracking & the return-to-run ladder ──────────────────────────────────
def injury_snapshot(home: Optional[str] = None) -> Dict[str, Any]:
    """Compact active-injury state (mode, load_cap_pct, allowed_types, primary episode) — the
    single view the plan guardrail and coach context read. ``active=False`` when clear."""
    return _injury.snapshot(resolve_home(home))


def injury_episodes(home: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every injury episode, newest onset first."""
    return _injury.all_episodes(resolve_home(home))


def injury_parse(text: str) -> Optional[Dict[str, Any]]:
    """Conservatively PROPOSE an injury episode from free text (needs a body part + a pain cue),
    or None. The coach confirms before ``injury_create`` persists it — never auto-write."""
    return _injury.parse_mention(text)


def injury_create(home: Optional[str] = None, **proposal) -> Dict[str, Any]:
    """Persist a confirmed episode. ``proposal`` keys: body_part (required), side, severity,
    onset_date, phase, note. Returns the stored episode (with its return-to-run phase)."""
    return _injury.create_episode(resolve_home(home, create=True), proposal)


def injury_checkin(home: Optional[str] = None, *, episode_id: str, pain_during: int = 0,
                   pain_after: int = 0, ran: bool = False, note: str = "") -> Optional[Dict[str, Any]]:
    """Record a recovery check-in; the deterministic ladder advances/steps-back the phase."""
    return _injury.checkin(resolve_home(home, create=True), episode_id, pain_during=pain_during,
                           pain_after=pain_after, ran=ran, note=note)


def injury_set_phase(home: Optional[str] = None, *, episode_id: str, phase: str) -> Optional[Dict[str, Any]]:
    """Force a return-to-run phase (rest/walk/walk_run/easy_only/build/full)."""
    return _injury.set_phase(resolve_home(home, create=True), episode_id, phase)


def injury_resolve(home: Optional[str] = None, *, episode_id: str) -> Optional[Dict[str, Any]]:
    """Mark an episode resolved (phase→full, cap→100%)."""
    return _injury.resolve(resolve_home(home, create=True), episode_id)


# ── Body — weight trend / race weight / fueling ────────────────────────────────
def body_trend(home: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Weight trend (current, rate kg/wk, direction) from body.jsonl, or None if too few logs."""
    return _body.trend(resolve_home(home))


def body_summary(home: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Compact body/fuel signal bundle (trend + race-weight + under-fueling) for coach context."""
    return _body.summary(resolve_home(home))


def log_weight(home: Optional[str] = None, *, weight_kg: float, bodyfat_pct: Optional[float] = None,
               note: Optional[str] = None, on_date: Optional[str] = None) -> Dict[str, Any]:
    """Append one weight entry to body.jsonl (one-tap input)."""
    return _body.log_weight(resolve_home(home, create=True), weight_kg, bodyfat_pct=bodyfat_pct,
                            note=note, on_date=on_date)


def set_target_weight(home: Optional[str] = None, kg: Optional[float] = None) -> Optional[float]:
    """Set (or clear, with kg=None) the race-weight target in goal.json — preserves the race goal."""
    return _body.set_target_weight(resolve_home(home, create=True), kg)


# ── Zones — HR zones + manual HRmax override ────────────────────────────────────
def zones(home: Optional[str] = None) -> Dict[str, Any]:
    """The runner's HR-zone table (from estimated or overridden HRmax) + per-zone pace estimates."""
    return _zones.current(resolve_home(home))


def set_hrmax(home: Optional[str] = None, value=None) -> Dict[str, Any]:
    """Persist a manual HRmax override into config.json (the core's analysis honors it)."""
    return _zones.set_hrmax(resolve_home(home, create=True), value)


def clear_hrmax(home: Optional[str] = None) -> Dict[str, Any]:
    """Drop the manual HRmax override (revert to estimation)."""
    return _zones.clear_hrmax(resolve_home(home, create=True))


# ── Weather — forecast + running advice (live query, cached 2h) ─────────────────
def weather_forecast(home: Optional[str] = None, force: bool = False) -> Optional[Dict[str, Any]]:
    """Forecast + air quality for the runner's saved location (Met.no + Open-Meteo AQI), cached
    2h in weather.json. None if no location is set. Live query — call once per runner intent."""
    return _weather.forecast(resolve_home(home), force=force)


def weather_advise(day: Dict[str, Any], workout_type: str = "") -> Dict[str, Any]:
    """Running advice (heat/cold/precip/AQI adjustments) for one forecast day from ``forecast``."""
    return _weather.advise(day, workout_type)


def weather_set_location(home: Optional[str] = None, *, place: str, lat: Optional[float] = None,
                         lon: Optional[float] = None, tz: Optional[str] = None) -> Dict[str, Any]:
    """Set + cache the runner's location in config.json (geocodes ``place`` if lat/lon omitted)."""
    return _weather.set_location(resolve_home(home, create=True), place, lat=lat, lon=lon, tz=tz)


# ── Weekly review — plan↔actual adherence (deterministic; narrative is the coach's) ──
def week_overview(home: Optional[str] = None, offset: int = 0) -> Dict[str, Any]:
    """One week's plan overlaid on actual runs → 7 day cells, each with an adherence verdict
    (done/skipped/upcoming/rest_kept/unplanned/skipped_injury/…). ``offset`` 0 = this week,
    <0 past, >0 future. Pure file reads; injury days are charitably marked recovery."""
    return _review.week_overview(resolve_home(home), offset)


def week_review_status(home: Optional[str] = None, offset: int = 0) -> Dict[str, Any]:
    """Is the week's training effectively complete (so a weekly review should surface)? ``ready``
    is True only when the last planned training day is today-or-past and done, nothing past-due is
    still pending, and ≥1 run was logged. A no-plan week is never auto-ready."""
    return _review.week_review_status(resolve_home(home), offset)


def week_review_aggregate(home: Optional[str] = None, offset: int = 0) -> Dict[str, Any]:
    """Deterministic weekly roll-up: planned↔actual volume, adherence %, key-session execution,
    per-day brief, goal + injury context. The numbers the coach's review narrative sits beside."""
    return _review.week_review_aggregate(resolve_home(home), offset)


def week_review_prompt(home: Optional[str] = None, offset: int = 0) -> str:
    """A grounded weekly-review prompt for the coach — reads the WEEK as a whole and gives one
    next-week DIRECTION (principle, not a prescription). Carries the no-prescription rule so the
    review never drifts into 'go run X today' — that's the weekly plan's job, not the review's."""
    home = resolve_home(home)
    return _review.week_review_prompt(home, _review.week_review_aggregate(home, offset))


# ── Insights — the "와우 모먼트" detector pipeline ──────────────────────────────────
def detect_insights(home: Optional[str] = None, max_cards: int = 8, deep: bool = True) -> List[Dict[str, Any]]:
    """Scan the full log + goal/profile/plan/PB/body for cross-activity trends, self-relative
    records, and hidden signals → score-ranked insight cards (highest first). Deterministic; never
    raises. ``deep=True`` lets the zone/decoupling detectors pull lap/stream signals for a few
    recent Strava runs via ``analyze_activity`` (≤4 calls, bounded — never bulk); ``deep=False``
    keeps it fully offline."""
    import insights as _insights  # lazy: larger detector package, only needed on demand
    home = resolve_home(home)
    analyze_fn = (lambda sid, h: analyze_activity(sid, home=h)) if deep else None
    return _insights.detect(home, max_cards=max_cards, analyze_fn=analyze_fn)
