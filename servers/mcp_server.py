#!/usr/bin/env python3
"""oh-my-personal-best — MCP server.

Exposes the OMPB deterministic toolkit (data import, Strava sync, training-log
queries, and the self-contained HTML report/week renderers) as Model Context
Protocol tools, plus a coaching system prompt. Any MCP host — Claude Desktop,
Cursor, Cline, VS Code, Gemini CLI, … — can then read and act on the runner's
training data without the Claude Code plugin.

What MCP does and doesn't give you: it provides the *tools* (deterministic,
provider-agnostic) and a coaching *prompt*. It does NOT enforce the multi-agent
safety gate (plan-critic) — that lives in the Claude Code plugin and the Agent
SDK app (apps/coach), where OMPB owns the orchestration loop. Treat this server
as the universal data layer.

Run:
    pip install "mcp[cli]"          # plus: pip install fitdecode  (for .fit import)
    python servers/mcp_server.py    # stdio transport

Wire into an MCP host (e.g. Claude Desktop ~/Library/Application Support/Claude/
claude_desktop_config.json):
    {
      "mcpServers": {
        "ompb": {
          "command": "python",
          "args": ["/ABSOLUTE/PATH/oh-my-personal-best/servers/mcp_server.py"],
          "env": { "OMPB_HOME": "/ABSOLUTE/PATH/.ompb" }
        }
      }
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# Make the repo's ompb_core importable whether run as a script or installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ompb_core as ompb  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - dependency hint
    sys.stderr.write('error: MCP SDK not installed. Run: pip install "mcp[cli]"\n')
    raise

mcp = FastMCP("oh-my-personal-best")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #

@mcp.tool()
def ompb_get_state(home: Optional[str] = None) -> str:
    """Snapshot the runner's state: profile (age/PBs/mileage), goal, current plan
    phase, app config (language), and training-log stats (count + date range).
    Call this first — every coaching judgment should be grounded in real state.

    Args:
        home: OMPB data dir. Omit to smart-resolve ($OMPB_HOME -> ~/.ompb -> ./.ompb).
    """
    return _json(ompb.get_state(home))


@mcp.tool()
def ompb_query_log(
    since: Optional[str] = None,
    until: Optional[str] = None,
    sport: Optional[str] = None,
    type: Optional[str] = None,
    limit: Optional[int] = None,
    home: Optional[str] = None,
) -> str:
    """Query training-log entries, date-sorted (oldest→newest).

    Args:
        since: inclusive lower bound 'YYYY-MM-DD'.
        until: inclusive upper bound 'YYYY-MM-DD'.
        sport: filter by sport (running/cycling/swimming/walking/hiking/…).
        type: filter by session type (easy/long/tempo/interval/recovery/race/cross/rest).
        limit: keep only the most recent N matching entries.
        home: OMPB data dir (smart-resolved if omitted).
    """
    return _json(ompb.query_log(home=home, since=since, until=until,
                                sport=sport, type=type, limit=limit))


@mcp.tool()
def ompb_weekly_load(weeks: int = 12, home: Optional[str] = None) -> str:
    """Per-ISO-week training load (distance_km + session count), last `weeks` weeks.
    Use to assess ramp rate, down weeks, and fatigue trends.

    Args:
        weeks: number of most-recent weeks to return.
        home: OMPB data dir (smart-resolved if omitted).
    """
    return _json(ompb.weekly_load(home=home, weeks=weeks))


@mcp.tool()
def ompb_report_data(home: Optional[str] = None) -> str:
    """The full structured analysis payload the HTML report is built from:
    athlete summary, totals, PBs, monthly volume, HR-by-pace, intensity mix,
    aerobic-efficiency series, and any saved diagnosis. Reason over this JSON to
    diagnose fitness or a limiter without rendering HTML.

    Args:
        home: OMPB data dir (smart-resolved if omitted).
    """
    return _json(ompb.report_data(home))


# --------------------------------------------------------------------------- #
# Write / render tools
# --------------------------------------------------------------------------- #

@mcp.tool()
def ompb_import_file(
    path: str,
    tz: Optional[str] = None,
    long_threshold: Optional[float] = None,
    home: Optional[str] = None,
) -> str:
    """Import a device export into the training log: a Garmin/COROS .fit file,
    .zip archive, or a directory of them — or a Strava-style .csv. De-duplicated
    (incl. cross-source). Returns the importer's summary.

    Args:
        path: file/dir to import (.fit/.zip/dir for devices, .csv for Strava export).
        tz: local timezone for .fit (e.g. 'Asia/Seoul'); default system local.
        long_threshold: km at/above which a run is typed 'long' (default 19).
        home: OMPB data dir (smart-resolved if omitted).
    """
    return ompb.import_file(path, home=home, tz=tz, long_threshold=long_threshold)


@mcp.tool()
def ompb_sync_strava(
    after: Optional[str] = None,
    max_pages: Optional[int] = None,
    home: Optional[str] = None,
) -> str:
    """Sync Strava activities into the log (auto-refreshes the stored token).
    Requires a prior one-time connect (strava.json in the home dir). Returns the
    sync summary (new / duplicates / by sport).

    Args:
        after: only activities on/after 'YYYY-MM-DD'.
        max_pages: cap pages fetched (200 activities/page).
        home: OMPB data dir (smart-resolved if omitted).
    """
    return ompb.sync_strava(home=home, after=after, max_pages=max_pages)


@mcp.tool()
def ompb_build_report(lang: Optional[str] = None, out: Optional[str] = None,
                      home: Optional[str] = None) -> str:
    """Render the comprehensive, self-contained HTML analysis report (inline SVG
    charts, print/PDF-ready). Returns the output file path.

    Args:
        lang: 'en' or 'ko' (default: config.json language, else 'en').
        out: output path (default: <home>/reports/report-<date>.html).
        home: OMPB data dir (smart-resolved if omitted).
    """
    return ompb.build_report(home=home, lang=lang, out=out)


@mcp.tool()
def ompb_build_week(lang: Optional[str] = None, plan: Optional[str] = None,
                    out: Optional[str] = None, home: Optional[str] = None) -> str:
    """Render this week's plan as a print-ready HTML card (from plan-week.json).
    Returns the output file path.

    Args:
        lang: 'en' or 'ko' (default: config.json language, else 'en').
        plan: plan-week.json path (default: <home>/plan-week.json).
        out: output path (default: <home>/weeks/week-<date>.html).
        home: OMPB data dir (smart-resolved if omitted).
    """
    return ompb.build_week(home=home, lang=lang, plan=plan, out=out)


# --------------------------------------------------------------------------- #
# Coaching prompt — adopt the OMPB persona in any MCP host
# --------------------------------------------------------------------------- #

@mcp.prompt()
def ompb_coach() -> str:
    """Load the oh-my-personal-best marathon-coaching system prompt."""
    return (
        "You are oh-my-personal-best, a marathon coaching assistant (10K / Half / Full).\n"
        "Zero learning curve: the runner speaks plainly; you route to the right judgment.\n\n"
        "ALWAYS load real state before advising: call ompb_get_state first, and "
        "ompb_weekly_load / ompb_report_data as needed. Never invent numbers.\n\n"
        "Safety first — any pain, injury, illness, dizziness, or chest symptom overrides "
        "every training prescription: stop prescribing load, advise rest/clearance, and "
        "escalate red flags to 'seek medical care now'. You are a coach, not a doctor; "
        "never diagnose medical conditions.\n\n"
        "Respect progressive overload: weekly volume increases capped at ~10%/week; flag "
        "unsafe ramps and inadequate tapers. A gap in the log is missing DATA, not missing "
        "training — if the latest entry is >4 days old, confirm the export isn't stale "
        "before judging fatigue or detraining.\n\n"
        "Reply in the runner's configured language (ompb_get_state -> config.language; "
        "en|ko). To produce artifacts, call ompb_build_report (analysis) or ompb_build_week "
        "(this week's card)."
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
