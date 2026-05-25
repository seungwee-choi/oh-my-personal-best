"""ompb_core exposed as Claude Agent SDK in-process tools.

Wraps the deterministic toolkit in ``@tool`` handlers and bundles them into an
in-process MCP server (``create_sdk_mcp_server``) so the coach app's orchestrator
and subagents can read and act on the runner's real training data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ompb_core as ompb  # noqa: E402

from claude_agent_sdk import create_sdk_mcp_server, tool  # noqa: E402

SERVER_NAME = "ompb"


def _text(value: Any) -> Dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _err(exc: Exception) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}


_OBJ = "object"


@tool("get_state", "Snapshot the runner's profile, goal, plan phase, config (language), "
                   "and training-log stats. Call first — ground advice in real state.",
      {"type": _OBJ, "properties": {"home": {"type": "string"}}, "required": []})
async def get_state(args):
    try:
        return _text(ompb.get_state(args.get("home")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("query_log", "Query training-log entries, date-sorted. Filters: since/until "
                   "(YYYY-MM-DD), sport, type, limit (most recent N).",
      {"type": _OBJ, "properties": {
          "since": {"type": "string"}, "until": {"type": "string"},
          "sport": {"type": "string"}, "type": {"type": "string"},
          "limit": {"type": "integer"}, "home": {"type": "string"}}, "required": []})
async def query_log(args):
    try:
        return _text(ompb.query_log(home=args.get("home"), since=args.get("since"),
                                    until=args.get("until"), sport=args.get("sport"),
                                    type=args.get("type"), limit=args.get("limit")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("weekly_load", "Per-ISO-week load (distance_km + sessions) for the last `weeks` "
                     "weeks. Use for ramp rate, down weeks, fatigue trends.",
      {"type": _OBJ, "properties": {"weeks": {"type": "integer"}, "home": {"type": "string"}},
       "required": []})
async def weekly_load(args):
    try:
        return _text(ompb.weekly_load(home=args.get("home"), weeks=args.get("weeks", 12)))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("report_data", "The full structured analysis payload (totals, PBs, monthly volume, "
                     "HR-by-pace, intensity mix, aerobic-efficiency series, diagnosis). "
                     "Reason over this to diagnose fitness/limiter.",
      {"type": _OBJ, "properties": {"home": {"type": "string"}}, "required": []})
async def report_data(args):
    try:
        return _text(ompb.report_data(args.get("home")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("import_file", "Import a Garmin/COROS .fit/.zip/directory or a Strava .csv into the "
                     "training log (de-duplicated). Returns the import summary.",
      {"type": _OBJ, "properties": {
          "path": {"type": "string"}, "tz": {"type": "string"},
          "long_threshold": {"type": "number"}, "home": {"type": "string"}},
       "required": ["path"]})
async def import_file(args):
    try:
        return _text(ompb.import_file(args["path"], home=args.get("home"),
                                      tz=args.get("tz"), long_threshold=args.get("long_threshold")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("sync_strava", "Sync Strava activities into the log (auto-refreshes token). Needs a "
                     "prior connect (strava.json). Returns the sync summary.",
      {"type": _OBJ, "properties": {
          "after": {"type": "string"}, "max_pages": {"type": "integer"},
          "home": {"type": "string"}}, "required": []})
async def sync_strava(args):
    try:
        return _text(ompb.sync_strava(home=args.get("home"), after=args.get("after"),
                                      max_pages=args.get("max_pages")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("build_report", "Render the comprehensive self-contained HTML analysis report "
                      "(inline SVG, print/PDF-ready). Returns the file path.",
      {"type": _OBJ, "properties": {
          "lang": {"type": "string"}, "out": {"type": "string"}, "home": {"type": "string"}},
       "required": []})
async def build_report(args):
    try:
        return _text(ompb.build_report(home=args.get("home"), lang=args.get("lang"),
                                       out=args.get("out")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


@tool("build_week", "Render this week's plan card (from plan-week.json) as print-ready HTML. "
                    "Returns the file path.",
      {"type": _OBJ, "properties": {
          "lang": {"type": "string"}, "plan": {"type": "string"},
          "out": {"type": "string"}, "home": {"type": "string"}}, "required": []})
async def build_week(args):
    try:
        return _text(ompb.build_week(home=args.get("home"), lang=args.get("lang"),
                                     plan=args.get("plan"), out=args.get("out")))
    except Exception as e:  # noqa: BLE001
        return _err(e)


OMPB_TOOLS = [get_state, query_log, weekly_load, report_data,
              import_file, sync_strava, build_report, build_week]

_TOOL_NAMES = ["get_state", "query_log", "weekly_load", "report_data",
               "import_file", "sync_strava", "build_report", "build_week"]

# Tool names as the model must reference them (mcp__<server>__<tool>).
ALLOWED_TOOL_NAMES = [f"mcp__{SERVER_NAME}__{n}" for n in _TOOL_NAMES]


def make_server():
    """The in-process MCP server bundling all OMPB tools."""
    return create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=OMPB_TOOLS)
