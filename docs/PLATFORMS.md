# Platform Expansion — beyond the Claude Code plugin

oh-my-personal-best started as a Claude Code plugin. This document covers running
the same coaching brain on **other platforms**, and the architecture that makes it
possible.

## The key fact: the valuable parts have zero AI-platform coupling

Measured against the code, OMPB separates cleanly into four layers:

| Layer | What | Coupling to Claude Code | Portable? |
|---|---|---|---|
| **Deterministic core** | `scripts/` (import, Strava sync, report/week renderers) + `templates/` + the JSON state schema | one ~15-line helper (`resolve_plugin_root`); **no** `anthropic`/Claude API calls; stdlib + optional `fitdecode` | ✅ ~100% |
| **Domain knowledge** | `agents/*.md`, `skills/*/SKILL.md`, `CLAUDE.md` routing | pure prompts / markdown | ✅ as content |
| **Orchestration glue** | subagent spawning, the plan-critic gate, parallel consults | Claude Code native | ❌ rebuild per platform |
| **Distribution** | `.claude-plugin/` manifest, marketplace | Claude Code only | ❌ per platform |

So portability isn't the blocker — re-implementing orchestration and picking a
distribution surface is. The crown jewels (data pipeline, HTML report, diagnosis
inputs) are already platform-neutral. `ompb_core` makes that explicit.

---

## `ompb_core` — the shared toolkit facade

One clean Python API over the deterministic toolkit, reused by every surface.

```python
import ompb_core as ompb

ompb.get_state()                       # profile + goal + plan + config + log stats
ompb.query_log(since="2026-01-01", type="long", limit=10)
ompb.weekly_load(weeks=12)             # per-ISO-week distance + sessions
ompb.report_data()                     # the structured REPORT_DATA payload
ompb.import_file("~/coros-export.zip") # .fit/.zip/dir or .csv -> training log
ompb.sync_strava(after="2026-01-01")   # auto-refreshes the stored token
ompb.build_report(lang="ko")           # -> path to self-contained HTML
ompb.build_week(lang="ko")             # -> path to the weekly card
```

Read paths import the script helpers in-process; write/render paths invoke the
scripts as subprocesses (faithful to their CLI contract — dedup, integrity guards,
summaries). Standard library only.

---

## Surface 1 — MCP server (`servers/mcp_server.py`)

Exposes the toolkit as Model Context Protocol tools + a coaching prompt, so **any
MCP host** (Claude Desktop, Cursor, Cline, VS Code, Gemini CLI, …) can read and act
on the runner's data. One build, many clients.

```bash
pip install "mcp[cli]" fitdecode
python servers/mcp_server.py        # stdio
```

Wire into Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ompb": {
      "command": "python",
      "args": ["/ABS/PATH/oh-my-personal-best/servers/mcp_server.py"],
      "env": { "OMPB_HOME": "/ABS/PATH/.ompb" }
    }
  }
}
```

Tools: `ompb_get_state`, `ompb_query_log`, `ompb_weekly_load`, `ompb_report_data`,
`ompb_import_file`, `ompb_sync_strava`, `ompb_build_report`, `ompb_build_week`.
Prompt: `ompb_coach` (the coaching persona + safety rules).

**Limitation:** MCP provides tools + a prompt, not orchestration. The multi-agent
safety gate (plan-critic, never-self-approve) is **not** enforced here — that lives
in the plugin and in Surface 2. Treat the MCP server as the universal data layer.

---

## Surface 2 — Claude Agent SDK app (`apps/coach/`)

A standalone CLI that **owns the orchestration loop**, so the gate is preserved.
It reuses the plugin's routing (`CLAUDE.md`), the eight specialists (`agents/*.md`
→ `AgentDefinition`, with their per-agent model routing and read-only gating), and
`ompb_core` (as in-process Agent SDK tools).

```bash
pip install claude-agent-sdk fitdecode
export ANTHROPIC_API_KEY=sk-ant-...
python -m apps.coach.app                              # interactive
python -m apps.coach.app "what should I run today?"   # one-shot
```

- `agents.py` — parses `agents/*.md` into `AgentDefinition`s (model + gating preserved).
- `tools.py` — `ompb_core` wrapped as `@tool`s in an in-process MCP server.
- `app.py` — builds `ClaudeAgentOptions` (system prompt = `CLAUDE.md` + a runtime note,
  subagents, tools), runs an interactive / one-shot loop via `ClaudeSDKClient`.

This is the productization path: schedule it, wrap it in a service, or back a bot/web UI.

---

## Surface 3 — Discord bot (`apps/discord_bot/`) — end-user prototype

Brings the coach to where runners already hang out. DM the bot or @mention it in a
channel and speak plainly — natural-language messages route to the full Agent SDK
coach (Surface 2), so the routing brain, specialists, and plan-critic gate all apply.
Two convenience words attach artifacts: `week` / `주간` → the weekly card,
`report` / `리포트` → the analysis report.

```bash
pip install discord.py claude-agent-sdk fitdecode
export DISCORD_BOT_TOKEN=...      # Discord Developer Portal > Bot > Reset Token
export OMPB_HOME=/abs/path/.ompb  # the runner's data (single-tenant prototype)
python -m apps.discord_bot
```

Portal: enable the **Message Content Intent** (Bot settings); invite with the `bot`
scope + Send Messages / Attach Files. Agent SDK auth: a logged-in `claude` CLI or
`ANTHROPIC_API_KEY`.

**Prototype scope:** one shared `OMPB_HOME` (not per-Discord-user). Multi-tenant —
mapping each Discord user id to their own home — is the next step.

---

## Verification status

| Component | Status |
|---|---|
| `ompb_core` | ✅ verified live against the real 960-activity log (state/query/weekly/report_data + ko report render + error paths) |
| `agents.py` parsing | ✅ verified — 8/8 agents parse with correct model + read-only gating |
| **MCP server** | ✅ **live** — driven over stdio by the MCP client SDK (Python 3.12): `initialize` + 8 tools + `ompb_coach` prompt listed; `get_state` / `weekly_load` / `query_log` returned real data; `build_week` rendered the ko card (26 KB) |
| **Agent SDK app** | ✅ **live end-to-end** — `python -m apps.coach.app "…"` authenticated via the local `claude` CLI (Claude Code subscription, no API key needed), the orchestrator called `mcp__ompb__get_state`, and answered correctly **in Korean** (respecting `config.json` language) |
| **Discord bot** | ✅ logic + backbone verified (py3.12, discord.py 2.7.1): `route()` / `chunks()` unit-tested, `discord.Client` builds with the message-content intent, and the backing `ask()` returned a correct Korean answer from the real log. The gateway connect needs a bot token (manual, outside this box). |

Tested in a Python 3.12 venv: `python3.12 -m venv .venv && .venv/bin/pip install "mcp[cli]" claude-agent-sdk fitdecode`.

---

## On the map (not built yet — kept in mind)

- **End-user surfaces** (the real market — runners aren't in a terminal): the
  Discord bot above is the first (Surface 3, prototype). Still open: per-user
  multi-tenancy; a Strava webhook → auto-ingest + push the weekly card; more chat
  surfaces (KakaoTalk / Telegram); a web PWA reusing the self-contained HTML
  templates. All sit on Surface 2.
- **Provider-agnostic adapters** (OpenAI / Gemini / open models): prompts mostly
  transfer, but the limiter-diagnosis reasoning is Claude-tuned — port only after the
  diagnosis quality is re-validated per model (the beta lesson: a bad fitness anchor
  flips the diagnosis).
