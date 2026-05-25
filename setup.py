"""setuptools shim — bundle scripts/ + templates/ into the ompb_core package.

These directories must stay at the repo root for the Claude Code plugin
(`$CLAUDE_PLUGIN_ROOT/scripts`, and build scripts find `../templates`), so we can't
move them. Instead we COPY them into ompb_core/_bundled/ at build time, making the
installed wheel self-contained. The copy is git-ignored (the repo root stays the one
source of truth); ompb_core/core.py resolves the repo layout first, the bundle second.

All other metadata lives in pyproject.toml (PEP 621); this file only adds the copy step.
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).parent.resolve()
BUNDLE = ROOT / "ompb_core" / "_bundled"
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


class build_py_bundled(build_py):
    """Copy scripts/ and templates/ into ompb_core/_bundled/ before collecting package data."""

    def run(self):
        for sub in ("scripts", "templates"):
            src, dst = ROOT / sub, BUNDLE / sub
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, ignore=_IGNORE)
        super().run()


setup(cmdclass={"build_py": build_py_bundled})
