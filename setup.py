"""setuptools shim — bundle runtime assets into the packages at build time.

These files must stay at the repo root for the Claude Code plugin
(`$CLAUDE_PLUGIN_ROOT/scripts`, build scripts find `../templates`, the plugin reads
CLAUDE.md + agents/), so we can't move them. Instead we COPY them into the packages at
build time, making installed wheels self-contained:

  ompb_core/_bundled/{scripts,templates}   — the deterministic toolkit
  apps/coach/_bundled/{CLAUDE.md,agents}    — the coach's routing brain + specialists

The copies are git-ignored (the repo root stays the one source of truth); the
resolvers in ompb_core/core.py and apps/coach/_assets.py prefer the repo layout first,
the bundle second. All other metadata lives in pyproject.toml (PEP 621).
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).parent.resolve()
CORE_BUNDLE = ROOT / "ompb_core" / "_bundled"
COACH_BUNDLE = ROOT / "apps" / "coach" / "_bundled"
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def _copytree(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=_IGNORE)


class build_py_bundled(build_py):
    """Copy runtime assets into the packages before collecting package data."""

    def run(self):
        # ompb_core — deterministic toolkit
        for sub in ("scripts", "templates"):
            _copytree(ROOT / sub, CORE_BUNDLE / sub)
        # apps.coach — routing brain + agent definitions
        _copytree(ROOT / "agents", COACH_BUNDLE / "agents")
        claude_md = ROOT / "CLAUDE.md"
        if claude_md.is_file():
            COACH_BUNDLE.mkdir(parents=True, exist_ok=True)
            shutil.copy2(claude_md, COACH_BUNDLE / "CLAUDE.md")
        super().run()


setup(cmdclass={"build_py": build_py_bundled})
