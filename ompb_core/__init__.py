"""ompb_core — a provider-agnostic facade over the OMPB deterministic toolkit.

The crown jewels of oh-my-personal-best — the data importers, the state schema,
and the self-contained HTML report/week renderers — have *zero* AI-platform
coupling (standard-library Python + one optional dep, ``fitdecode``). This
package exposes them behind one clean Python API so any surface can reuse them:

    >>> import ompb_core as ompb
    >>> state = ompb.get_state()              # profile + goal + log stats
    >>> ompb.import_file("~/coros-export.zip") # .fit/.zip/.csv -> training log
    >>> path = ompb.build_report(lang="ko")    # render the analysis report

Read paths import the script helpers in-process; write/render paths invoke the
scripts as subprocesses (faithful to their CLI contract, isolating argv/stderr).

Consumers built on this core:
  - servers/mcp_server.py   — an MCP server (Claude Desktop / Cursor / Cline / …)
  - apps/coach/             — a standalone Claude Agent SDK coaching app
"""

from .core import (
    OMPBError,
    resolve_home,
    resolve_lang,
    get_state,
    query_log,
    weekly_load,
    report_data,
    import_file,
    sync_strava,
    build_report,
    build_week,
    build_activity,
    reclassify,
    analyze_activity,
    export_report,
    injury_snapshot,
    injury_episodes,
    injury_parse,
    injury_create,
    injury_checkin,
    injury_set_phase,
    injury_resolve,
    body_trend,
    body_summary,
    log_weight,
    set_target_weight,
    zones,
    set_hrmax,
    clear_hrmax,
    weather_forecast,
    weather_advise,
    weather_set_location,
    week_overview,
    week_review_status,
    week_review_aggregate,
    week_review_prompt,
    detect_insights,
)

__all__ = [
    "OMPBError",
    "resolve_home",
    "resolve_lang",
    "get_state",
    "query_log",
    "weekly_load",
    "report_data",
    "import_file",
    "sync_strava",
    "build_report",
    "build_week",
    "build_activity",
    "reclassify",
    "analyze_activity",
    "export_report",
    # injury
    "injury_snapshot",
    "injury_episodes",
    "injury_parse",
    "injury_create",
    "injury_checkin",
    "injury_set_phase",
    "injury_resolve",
    # body / fuel
    "body_trend",
    "body_summary",
    "log_weight",
    "set_target_weight",
    # zones
    "zones",
    "set_hrmax",
    "clear_hrmax",
    # weather
    "weather_forecast",
    "weather_advise",
    "weather_set_location",
    # weekly review
    "week_overview",
    "week_review_status",
    "week_review_aggregate",
    "week_review_prompt",
    # insights
    "detect_insights",
]

__version__ = "0.1.0"
