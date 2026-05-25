"""Locate the coach's runtime assets — CLAUDE.md (routing brain) and agents/*.md.

Like ompb_core's toolkit, these live at the repo root for the Claude Code plugin and
are copied into apps/coach/_bundled/ at build time (see setup.py), so an installed
wheel is self-contained. Resolve the repo layout first (dev edits win), the bundle second.
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent        # <repo>/apps/coach  (or .../site-packages/apps/coach)
REPO_ROOT = _HERE.parents[1]                    # repo root: coach -> apps -> root
_BUNDLE = _HERE / "_bundled"


def claude_md() -> Path:
    """Path to CLAUDE.md (the natural-language routing brain)."""
    for cand in (REPO_ROOT / "CLAUDE.md", _BUNDLE / "CLAUDE.md"):
        if cand.is_file():
            return cand
    return REPO_ROOT / "CLAUDE.md"  # default; a clear error follows if truly absent


def agents_dir() -> Path:
    """Directory of agent definitions (agents/*.md)."""
    for cand in (REPO_ROOT / "agents", _BUNDLE / "agents"):
        if cand.is_dir():
            return cand
    return REPO_ROOT / "agents"
