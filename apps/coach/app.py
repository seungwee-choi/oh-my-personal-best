#!/usr/bin/env python3
"""oh-my-personal-best — standalone coaching app on the Claude Agent SDK.

Runs the OMPB coach outside Claude Code: the same routing brain (CLAUDE.md),
the same eight specialist subagents (agents/*.md), and the same deterministic
toolkit (ompb_core) — but as a plain CLI you can run anywhere, schedule, or wrap
in a service/bot. Unlike the MCP server, this app OWNS the orchestration loop, so
the never-self-approve safety gate (plan-critic) is preserved.

Setup:
    pip install claude-agent-sdk          # + pip install fitdecode  (for .fit import)
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python -m apps.coach.app                 # interactive
    python -m apps.coach.app "what should I run today?"   # one-shot
    OMPB_HOME=/path/to/.ompb python -m apps.coach.app
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )
except ModuleNotFoundError:
    sys.stderr.write("error: Agent SDK not installed. Run: pip install claude-agent-sdk\n")
    raise

from apps.coach.agents import load_agents
from apps.coach.tools import ALLOWED_TOOL_NAMES, SERVER_NAME, make_server

SDK_APPENDIX = f"""

---
RUNTIME: You are running as a standalone Claude Agent SDK app, NOT inside Claude Code.
- There are no slash commands here. Infer intent from natural language using the routing
  table above, and orchestrate the specialists yourself.
- The eight specialists are available as subagents via the Task tool (race-analyst,
  data-logger, plan-architect, session-coach, pace-strategist, physio-advisor,
  fuel-advisor, plan-critic). Honor the gate: a plan reaches the runner only after
  plan-critic approves — never self-approve.
- Read and act on the runner's real data with the mcp__{SERVER_NAME}__* tools
  (get_state, query_log, weekly_load, report_data, import_file, sync_strava,
  build_report, build_week). Always load state before advising.
- Skills (race-plan, weekly-adapt, race-week, pb-report, pb-week) are workflow recipes,
  not commands here — follow their agent sequence from CLAUDE.md to reproduce them.
"""


def build_options() -> ClaudeAgentOptions:
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    return ClaudeAgentOptions(
        system_prompt=claude_md + SDK_APPENDIX,
        model="opus",  # the orchestrator; subagents carry their own model from agents/*.md
        agents=load_agents(),
        mcp_servers={SERVER_NAME: make_server()},
        allowed_tools=[*ALLOWED_TOOL_NAMES, "Task", "Read"],
        permission_mode="acceptEdits",
        cwd=str(REPO_ROOT),
        setting_sources=None,  # don't inherit host CLAUDE.md/settings; this app is self-contained
    )


async def _stream(client: "ClaudeSDKClient") -> None:
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)
        elif isinstance(msg, ResultMessage):
            print()  # end the turn


async def run_once(prompt: str) -> None:
    async with ClaudeSDKClient(options=build_options()) as client:
        await client.query(prompt)
        await _stream(client)


async def run_interactive() -> None:
    state_home = os.environ.get("OMPB_HOME", "smart-resolve (~/.ompb -> ./.ompb)")
    print("oh-my-personal-best — coach (Agent SDK). Data home:", state_home)
    print("Speak plainly (e.g. \"what should I run today?\"). Ctrl-D or 'exit' to quit.\n")
    async with ClaudeSDKClient(options=build_options()) as client:
        while True:
            try:
                user = input("runner› ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user:
                continue
            if user.lower() in {"exit", "quit", ":q"}:
                break
            await client.query(user)
            await _stream(client)
            print()


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("warning: ANTHROPIC_API_KEY is not set — the SDK will fail to authenticate.\n")
    prompt = " ".join(sys.argv[1:]).strip()
    try:
        asyncio.run(run_once(prompt) if prompt else run_interactive())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
