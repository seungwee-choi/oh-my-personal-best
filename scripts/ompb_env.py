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
import sys
from datetime import datetime


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


def write_config(home, updates):
    """Merge ``updates`` into $OMPB_HOME/config.json and persist (preserving other keys, e.g.
    language). Existing settings the caller didn't touch are kept. Best-effort: a failed write
    must not crash a coaching turn — returns the merged dict it attempted to write."""
    cfg = read_config(home)
    cfg.update(updates)
    p = os.path.join(home, "config.json")
    try:
        os.makedirs(home, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return cfg


def local_today(tz="Asia/Seoul"):
    """The runner-local 'today' as a ``datetime.date``.

    OMPB stores activity dates in the runner's local calendar (KST in the reference
    deployment), and onset/relative-date parsing ("어제", "N일째") and "is the export stale?"
    checks must agree with that calendar — UTC ``date.today()`` rolls over at the wrong hour.
    Uses the stdlib zoneinfo when available, else a fixed +9h offset for the default KST tz.
    """
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(tz)).date()
    except Exception:  # noqa: BLE001 — no tzdata / unknown tz → fixed-offset fallback
        offset = 9 if tz == "Asia/Seoul" else 0
        return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=offset)).date()


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
            if os.path.isdir(cwd_home) and cwd_home != user_home:
                sys.stderr.write(
                    f"# warning: using {user_home}, but {cwd_home} also exists and is being "
                    f"ignored. Set OMPB_HOME (e.g. `export OMPB_HOME={cwd_home}`) to choose, "
                    f"or merge the two homes.\n")
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


def resolve_plugin_root():
    """Locate the plugin root (the dir containing scripts/ and templates/).

    $CLAUDE_PLUGIN_ROOT is not always exported into the shell that runs scripts, so don't
    rely on it: prefer the parent of this file's own directory (scripts live in <root>/scripts/,
    true for both the repo checkout and an installed plugin), then fall back to env / marketplace
    cache candidates.
    """
    here = os.path.dirname(os.path.abspath(__file__))           # <root>/scripts
    cand = os.path.dirname(here)
    if os.path.isdir(os.path.join(cand, "scripts")):
        return cand
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env and os.path.isdir(os.path.join(env, "scripts")):
        return env
    for base in ("~/.claude-personal/plugins/marketplaces/ompb",
                 "~/.claude/plugins/marketplaces/ompb"):
        p = os.path.expanduser(base)
        if os.path.isdir(os.path.join(p, "scripts")):
            return p
    return cand


# --- cross-source de-duplication --------------------------------------------
# Activities synced from two sources (e.g. a COROS .fit run also auto-pushed to Strava,
# or a watch + phone uploading the same run) get different source_ids, so source_id-only
# dedup misses them. The fingerprint groups them by START TIME: two uploads of one run
# start within a few seconds of each other, so a 1-minute time bucket catches them — while
# a *different* session the same day (warm-up vs main set, even at the same distance) lands
# in a different bucket. This replaced a (date, distance) fingerprint that wrongly merged
# distinct same-distance sessions AND split one run whose two uploads measured slightly
# different GPS distances (e.g. 2150 m vs 2154 m rounding to 2.1 vs 2.2).

_FP_BUCKET = 60  # seconds — group an activity's start time into 1-minute buckets


def _epoch(iso):
    """ISO-8601 datetime string → POSIX seconds (float), or None. Accepts a trailing 'Z'."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def entry_fingerprint(entry):
    """A cross-source/duplicate-upload fingerprint. Prefers a start-time bucket
    ``('t', sport, minute_bucket)`` from ``started_at`` (UTC); pre-existing log entries
    without ``started_at`` fall back to ``('d', date, distance)`` so old logs still dedup.
    dup_kind() treats adjacent time buckets as the same run (see below)."""
    ep = _epoch(entry.get("started_at"))
    if ep is not None:
        return ("t", entry.get("sport"), int(ep // _FP_BUCKET))
    a = entry.get("actual") or {}
    d = a.get("distance_km")
    if entry.get("date") and d:
        return ("d", entry["date"], round(float(d), 1))
    return None


def load_seen(path):
    """Return {'ids': set, 'prints': set} of source_ids and fingerprints already in the log."""
    seen = {"ids": set(), "prints": set()}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("source_id"):
                    seen["ids"].add(o["source_id"])
                fp = entry_fingerprint(o)
                if fp:
                    seen["prints"].add(fp)
    return seen


def dup_kind(seen, entry):
    """Return 'id', 'cross-source', or None for a candidate entry against `seen`."""
    if entry.get("source_id") and entry["source_id"] in seen["ids"]:
        return "id"
    fp = entry_fingerprint(entry)
    if not fp:
        return None
    if fp[0] == "t":
        # Adjacent minute buckets count as the same run: a ~1 s gap can straddle a bucket
        # edge, and the two uploads' clocks can differ by a second or two.
        for db in (-1, 0, 1):
            if ("t", fp[1], fp[2] + db) in seen["prints"]:
                return "cross-source"
        return None
    if fp in seen["prints"]:
        return "cross-source"
    return None


def mark_seen(seen, entry):
    if entry.get("source_id"):
        seen["ids"].add(entry["source_id"])
    fp = entry_fingerprint(entry)
    if fp:
        seen["prints"].add(fp)


REPO_URL = "https://github.com/seungwee-choi/oh-my-personal-best"


def star_cta(home, lang="en", stream=None):
    """Print a one-time GitHub-star call-to-action, only after real value was delivered.

    Honest-CTA contract: the caller invokes this *after* producing a genuine artifact
    (a report, a week card, a sync that actually added activities). It fires at most once
    ever — a flag file ($OMPB_HOME/.star-prompted) suppresses it thereafter — never blocks,
    and is permanently silenced by setting OMPB_NO_CTA. Any failure is swallowed: a star
    nudge must never disrupt the command that called it.
    """
    if stream is None:
        stream = sys.stderr
    if os.environ.get("OMPB_NO_CTA"):
        return
    flag = os.path.join(home, ".star-prompted")
    if os.path.exists(flag):
        return
    if lang == "ko":
        msg = ("\n⭐ oh-my-personal-best가 도움이 됐다면, GitHub 스타가 다른 러너들에게 큰 힘이 됩니다:\n"
               f"   {REPO_URL}\n"
               "   (최초 1회만 표시 · OMPB_NO_CTA=1 로 끌 수 있어요)\n")
    else:
        msg = ("\n⭐ Enjoying oh-my-personal-best? A GitHub star helps other runners find it:\n"
               f"   {REPO_URL}\n"
               "   (shown once · silence with OMPB_NO_CTA=1)\n")
    try:
        stream.write(msg)
        import datetime as _dt
        with open(flag, "w", encoding="utf-8") as fh:
            fh.write(_dt.datetime.now().isoformat(timespec="seconds") + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Resolve and print the OMPB_HOME data directory.")
    ap.add_argument("--home", help="Explicit home override.")
    ap.add_argument("--print-home", action="store_true", help="Print the resolved home and exit.")
    ap.add_argument("--create", action="store_true", help="Create the home directory if missing.")
    a = ap.parse_args()
    print(resolve_home(a.home, create=a.create))
