#!/usr/bin/env python3
"""oh-my-personal-best — Discord bot (end-user surface prototype).

Brings the coach to where runners already hang out. DM the bot, or @mention it in
a channel, and speak plainly — "what should I run today?", "무릎이 좀 아픈데 롱런 해도 돼?".
Natural-language messages route to the full Agent SDK coach (apps/coach), so the
same routing brain, specialists, and plan-critic gate apply. Two convenience words
attach artifacts: "week" / "주간" → the weekly card, "report" / "리포트" → the analysis report.

Setup:
    pip install discord.py claude-agent-sdk        # + fitdecode for .fit import
    export DISCORD_BOT_TOKEN=...      # Discord Developer Portal > Bot > Reset Token
    export OMPB_HOME=/abs/path/.ompb  # the runner's data (single-tenant prototype)
    # Agent SDK auth: either a logged-in `claude` CLI, or ANTHROPIC_API_KEY.

Discord portal: enable the "Message Content Intent" (Bot settings), and invite the
bot with the `bot` scope + Send Messages / Attach Files / Read Message History.

Run:
    python -m apps.discord_bot

Prototype scope: one shared OMPB_HOME (not per-Discord-user). Multi-tenant — mapping
each Discord user id to their own home — is the next step.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ompb_core as ompb  # noqa: E402

try:
    import discord  # noqa: E402
except ModuleNotFoundError:
    sys.stderr.write("error: discord.py not installed. Run: pip install discord.py\n")
    raise

from apps.coach.app import ask  # noqa: E402

DISCORD_MAX = 2000
# Whole-message convenience shortcuts (matched against the trimmed message so a
# sentence like "how was last week?" still routes to the coach, not the card).
WEEK_CMDS = {"week", "weekly", "this week", "주간", "주간 계획", "주간계획", "이번 주", "훈련표"}
REPORT_CMDS = {"report", "리포트", "분석", "분석 리포트", "분석리포트", "pdf", "assessment"}

HELP = ('러너님, 무엇을 도와드릴까요? 예: "오늘 뭐 뛰어?" · "이번 주 계획 조정해줘" · '
        '"week"(주간 카드) · "report"(분석 리포트)')


def route(content: str) -> Tuple[str, str]:
    """Pure routing decision → ('week' | 'report' | 'chat', cleaned_content)."""
    low = content.strip().lower()
    if low in WEEK_CMDS:
        return ("week", content)
    if low in REPORT_CMDS:
        return ("report", content)
    return ("chat", content)


def chunks(text: str, size: int = DISCORD_MAX - 100) -> list[str]:
    """Split a reply into Discord-sized messages (2000-char limit)."""
    text = (text or "").strip() or "(no response)"
    return [text[i:i + size] for i in range(0, len(text), size)]


def _strip_mention(content: str, user_id: int) -> str:
    return content.replace(f"<@{user_id}>", "").replace(f"<@!{user_id}>", "").strip()


def make_client() -> "discord.Client":
    intents = discord.Intents.default()
    intents.message_content = True  # privileged: enable in the Developer Portal
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"[ompb] logged in as {client.user} (id {client.user.id})")

    @client.event
    async def on_message(message: "discord.Message"):
        if message.author.bot:
            return
        is_dm = message.guild is None
        mentioned = client.user in message.mentions
        if not (is_dm or mentioned):
            return

        content = message.content
        if mentioned:
            content = _strip_mention(content, client.user.id)
        if not content.strip():
            await message.channel.send(HELP)
            return

        kind, text = route(content)
        try:
            async with message.channel.typing():
                if kind == "week":
                    path = await asyncio.to_thread(ompb.build_week)
                    await message.channel.send("이번 주 훈련 카드입니다 📅", file=discord.File(path))
                    return
                if kind == "report":
                    path = await asyncio.to_thread(ompb.build_report)
                    await message.channel.send("분석 리포트입니다 📊", file=discord.File(path))
                    return
                answer = await ask(text)
            for part in chunks(answer):
                await message.channel.send(part)
        except Exception as exc:  # noqa: BLE001 — surface failures to the user, keep the bot alive
            await message.channel.send(f"⚠️ 처리 중 오류가 발생했어요: {exc}")

    return client


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.stderr.write("error: DISCORD_BOT_TOKEN is not set "
                         "(Discord Developer Portal > your app > Bot > Reset Token).\n")
        return 2
    make_client().run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
