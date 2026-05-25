#!/usr/bin/env python3
"""
Shared path resolution for oh-my-personal-best (OMPB) scripts.

OMPB_HOME is where the runner's state lives (training-log.jsonl, goal.json, reports/, ...).
It is resolved with this precedence (smart resolve):
  1. explicit argument (--home)
  2. $OMPB_HOME environment variable
  3. ~/.ompb        (if it already exists)
  4. ./.ompb        (if it already exists — backward compatibility)
  5. ~/.ompb        (default; created on demand)

This lets the plugin work from any directory (data in ~/.ompb) while still picking up an
existing project-local ./.ompb. Plugin *scripts* live under $CLAUDE_PLUGIN_ROOT/scripts and
are invoked by absolute path; this module is imported by sibling scripts (Python puts the
script's own directory on sys.path when run directly, so `from ompb_env import ...` works).
"""
import json
import os


def read_config(home):
    """Read $OMPB_HOME/config.json (app settings, e.g. language). Returns {} if absent/invalid."""
    p = os.path.join(home, "config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def resolve_lang(explicit, home):
    """Output/communication language: explicit flag > config.json `language` > 'en'."""
    if explicit in ("en", "ko"):
        return explicit
    lang = read_config(home).get("language")
    return lang if lang in ("en", "ko") else "en"


def resolve_home(explicit=None, create=False):
    """Return the absolute OMPB_HOME path per the documented precedence."""
    if explicit:
        home = os.path.abspath(os.path.expanduser(explicit))
    elif os.environ.get("OMPB_HOME"):
        home = os.path.abspath(os.path.expanduser(os.environ["OMPB_HOME"]))
    else:
        user_home = os.path.abspath(os.path.expanduser("~/.ompb"))
        cwd_home = os.path.abspath("./.ompb")
        if os.path.isdir(user_home):
            home = user_home
        elif os.path.isdir(cwd_home):
            home = cwd_home
        else:
            home = user_home  # default target for a fresh setup
    if create:
        os.makedirs(home, exist_ok=True)
    return home


def log_path(home):
    return os.path.join(home, "training-log.jsonl")


def state_path(home, name):
    return os.path.join(home, name)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Resolve and print the OMPB_HOME data directory.")
    ap.add_argument("--home", help="Explicit home override.")
    ap.add_argument("--print-home", action="store_true", help="Print the resolved home and exit.")
    ap.add_argument("--create", action="store_true", help="Create the home directory if missing.")
    a = ap.parse_args()
    print(resolve_home(a.home, create=a.create))
