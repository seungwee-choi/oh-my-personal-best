"""Load the plugin's eight specialist agents (agents/*.md) as Agent SDK subagents.

The agent prompts are platform-agnostic content: a YAML-ish frontmatter
(name / description / model / disallowedTools) plus an ``<Agent_Prompt>`` body.
This turns each into a ``claude_agent_sdk.AgentDefinition`` so the standalone
coach app spawns the exact same specialists — race-analyst, plan-critic, … —
that the Claude Code plugin does, including their per-agent model routing and
read-only gating.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from claude_agent_sdk import AgentDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"


def _parse(path: Path) -> Tuple[Dict[str, str], str]:
    """Return (frontmatter dict, body) for an agent markdown file."""
    text = path.read_text(encoding="utf-8")
    fm: Dict[str, str] = {}
    body = text
    if text.startswith("---"):
        # "" / frontmatter / body
        _, raw, body = text.split("---", 2)
        for line in raw.strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                fm[key.strip()] = val.strip()
    return fm, body.strip()


def load_agents(agents_dir: Path = AGENTS_DIR) -> Dict[str, AgentDefinition]:
    """Map agent name -> AgentDefinition for every agents/*.md file."""
    agents: Dict[str, AgentDefinition] = {}
    for path in sorted(agents_dir.glob("*.md")):
        fm, body = _parse(path)
        name = fm.get("name") or path.stem
        disallowed = [t.strip() for t in fm.get("disallowedTools", "").split(",") if t.strip()]
        agents[name] = AgentDefinition(
            description=fm.get("description", name),
            prompt=body,
            model=fm.get("model"),  # "opus" | "sonnet" | "haiku" | None (inherit)
            disallowedTools=disallowed or None,
        )
    return agents


if __name__ == "__main__":  # quick introspection: `python -m apps.coach.agents`
    for n, a in load_agents().items():
        ro = "read-only" if (a.disallowedTools and "Write" in a.disallowedTools) else "read-write"
        print(f"{n:16} model={a.model or 'inherit':7} {ro}  — {a.description[:60]}")
