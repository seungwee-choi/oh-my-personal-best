#!/usr/bin/env python3
"""
import_fit.py — Normalize COROS / Garmin .fit activity files into OMPB training-log JSONL.

COROS Training Hub exports raw Garmin FIT binary files (one per activity, named by
activity id), not CSV. This reads the per-activity `session` summary message from each
.fit file and emits one normalized training-log line per session to stdout.

Running activities are typed easy/long by distance; all other sports (cycling, swimming,
walking, hiking, ...) are recorded as `cross` so total training load is captured for
fatigue / overtraining analysis. Pace and cadence are only emitted for running, where
they are meaningful.

Each emitted line carries `source: "fit"` and `source_id: "<filename stem>"` so repeated
imports can be de-duplicated idempotently (see --dedup-against).

Requires: fitdecode (`pip install fitdecode`). FIT is a binary format; it cannot be
parsed with the standard library alone.

Usage:
    python3 import_fit.py <path...> [options]      paths: .fit | .zip | directory
    python3 import_fit.py ~/coros/ --tz Asia/Seoul      # appends directly to the resolved home log
    # (use --stdout to emit JSONL to stdout instead of writing the home log)

Options:
    --tz <name>               Local timezone for the activity date (default: system local).
    --long-threshold <km>     Running distance >= this is typed "long" (default: 19).
    --dedup-against <jsonl>    Skip activities whose source_id already appears in this log.
    --no-reclassify-generic    Keep COROS 'generic' activities as cross. By default, generic
                               activities with running evidence (foot dynamics or a 2:30–9:00/km
                               pace) are reclassified to running; such entries carry
                               `reclassified_from_sport: "generic"` for audit.
    --quiet                   Suppress the per-sport summary on stderr.
"""

import argparse
import datetime as dt
import glob
import json
import os
import sys
import tempfile
import warnings
import zipfile
from typing import Iterator, Optional, Tuple

from ompb_env import resolve_home, log_path, load_seen, dup_kind, mark_seen

try:
    import fitdecode
except ImportError:
    sys.stderr.write(
        "error: fitdecode is required to parse .fit files.\n"
        "       install it with:  pip install fitdecode\n"
    )
    sys.exit(2)

# COROS FIT files carry custom developer fields that trip fitdecode's size validation
# with harmless UserWarnings. Silence them so stderr stays clean for the summary.
warnings.filterwarnings("ignore", category=UserWarning, module="fitdecode")

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _get(msg, name, fallback=None):
    """Safe field access for a fitdecode data message."""
    try:
        if msg.has_field(name):
            v = msg.get_value(name, fallback=fallback)
            return v if v is not None else fallback
    except (KeyError, Exception):
        return fallback
    return fallback


def _local_date(start_time, tz: Optional["dt.tzinfo"]) -> Optional[str]:
    """Convert a FIT (UTC, tz-aware) start_time to a local YYYY-MM-DD date string."""
    if not isinstance(start_time, dt.datetime):
        return None
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=dt.timezone.utc)
    local = start_time.astimezone(tz) if tz is not None else start_time.astimezone()
    return local.date().isoformat()


def _pace_from_speed(speed_mps: Optional[float]) -> Optional[str]:
    """MM:SS per km from m/s, with a 2:00–20:00/km sanity bound."""
    if not speed_mps or speed_mps <= 0:
        return None
    secs_per_km = 1000.0 / speed_mps
    if not (120 <= secs_per_km <= 1200):
        return None
    return f"{int(secs_per_km // 60)}:{int(secs_per_km % 60):02d}"


def _running_cadence(msg) -> Optional[int]:
    """Steps/min for running. COROS reports avg_running_cadence as one-leg strides/min."""
    val = _get(msg, "avg_running_cadence")
    if val is None:
        val = _get(msg, "avg_cadence")
    if val is None:
        return None
    val = int(val)
    if val <= 0:
        return None
    if val < 120:  # one-leg strides/min -> both-leg steps/min
        val *= 2
    return val if 100 <= val <= 250 else None


# ---------------------------------------------------------------------------
# Session -> training-log entry
# ---------------------------------------------------------------------------

def classify(sport: Optional[str], distance_km: Optional[float], long_threshold: float) -> Tuple[str, str]:
    """Return (sport, ompb_type). Running -> easy/long by distance; everything else -> cross."""
    if sport == "running":
        if distance_km is not None and distance_km >= long_threshold:
            return "running", "long"
        return "running", "easy"
    return (sport or "unknown"), "cross"


def looks_like_running(msg, distance_km: Optional[float], speed_mps: Optional[float]) -> bool:
    """Heuristic: is a `sport='generic'` activity actually a run?

    COROS leaves some runs untagged as `generic`. They are distinguished from gym /
    indoor / misc activities (which sit in the same bucket at 11–70 min/km with no foot
    dynamics) by positive running evidence:
      - foot dynamics present (avg_step_length / avg_running_cadence / total_strides > 0), OR
      - a running-range average pace of 2:30–9:00 /km (speed 1.85–6.70 m/s).
    A 1 km floor avoids reclassifying tiny GPS fragments.
    """
    if not distance_km or distance_km < 1.0:
        return False
    cad = _get(msg, "avg_running_cadence")
    strides = _get(msg, "total_strides")
    steplen = _get(msg, "avg_step_length")
    foot_evidence = bool((cad and cad > 0) or (strides and strides > 0) or (steplen and steplen > 0))
    running_pace = bool(speed_mps and 1.85 <= speed_mps <= 6.70)  # 9:00/km .. 2:30/km
    return foot_evidence or running_pace


def session_to_entry(msg, source_id: str, tz, long_threshold: float,
                     reclassify_generic: bool = True) -> Optional[dict]:
    start = _get(msg, "start_time")
    date = _local_date(start, tz)
    if date is None:
        return None  # cannot place it on the calendar — skip

    dist_m = _get(msg, "total_distance")
    distance_km = round(dist_m / 1000.0, 3) if dist_m else None
    speed = _get(msg, "enhanced_avg_speed") or _get(msg, "avg_speed")

    raw_sport = _get(msg, "sport")
    sport_for_class = raw_sport
    reclassified_from = None
    if reclassify_generic and raw_sport == "generic" and looks_like_running(msg, distance_km, speed):
        sport_for_class = "running"
        reclassified_from = "generic"

    sport, ompb_type = classify(sport_for_class, distance_km, long_threshold)
    is_run = sport == "running"

    duration = _get(msg, "total_timer_time") or _get(msg, "total_elapsed_time")
    duration_s = int(round(duration)) if duration else None

    ascent = _get(msg, "total_ascent")
    cals = _get(msg, "total_calories")
    avg_hr = _get(msg, "avg_heart_rate")
    max_hr = _get(msg, "max_heart_rate")

    actual = {
        "distance_km": distance_km,
        "pace": _pace_from_speed(speed) if is_run else None,
        "avg_hr": int(avg_hr) if avg_hr else None,
        "max_hr": int(max_hr) if max_hr else None,
        "cadence": _running_cadence(msg) if is_run else None,
        "rpe": None,
        "duration_s": duration_s,
        "calories": int(cals) if cals else None,
        "ascent_m": int(ascent) if ascent is not None else None,
    }
    entry = {
        "date": date,
        "type": ompb_type,
        "planned": None,
        "actual": actual,
        "sport": sport,
        "source": "fit",
        "source_id": source_id,
        "logged_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if reclassified_from is not None:
        entry["reclassified_from_sport"] = reclassified_from  # provenance for audit
    return entry


def laps_from_fit(path: str):
    """Return (laps, total_distance_km) from a .fit file's `lap` messages, for analyze.py.

    Each lap → {distance_km, duration_s, pace_sec, avg_hr, max_hr}. Manual workout laps
    (varied distances) drive rep detection; auto-laps (≈1 km) the engine flags itself.
    """
    laps, total = [], 0.0
    with fitdecode.FitReader(path) as fr:
        for frame in fr:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "lap":
                dist_m = _get(frame, "total_distance")
                dur = _get(frame, "total_timer_time") or _get(frame, "total_elapsed_time")
                spd = _get(frame, "enhanced_avg_speed") or _get(frame, "avg_speed")
                km = dist_m / 1000.0 if dist_m else None
                laps.append({
                    "distance_km": round(km, 3) if km else None,
                    "duration_s": int(round(dur)) if dur else None,
                    "pace_sec": (1000.0 / spd) if spd and spd > 0 else None,
                    "avg_hr": int(_get(frame, "avg_heart_rate")) if _get(frame, "avg_heart_rate") else None,
                    "max_hr": int(_get(frame, "max_heart_rate")) if _get(frame, "max_heart_rate") else None,
                })
                if km:
                    total += km
    return laps, (round(total, 3) if total else None)


def streams_from_fit(path: str) -> dict:
    """Per-second streams from `record` messages: {time[s], heartrate, velocity[m/s], distance[m]}.
    For analyze.analyze_streams (decoupling / time-in-zone / hard efforts). Offline."""
    times, hr, vel, dist = [], [], [], []
    t0 = None
    with fitdecode.FitReader(path) as fr:
        for frame in fr:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "record":
                ts = _get(frame, "timestamp")
                sec = None
                if ts is not None and hasattr(ts, "timestamp"):
                    epoch = ts.timestamp()
                    if t0 is None:
                        t0 = epoch
                    sec = epoch - t0
                spd = _get(frame, "enhanced_speed")
                if spd is None:
                    spd = _get(frame, "speed")
                times.append(sec)
                hr.append(_get(frame, "heart_rate"))
                vel.append(spd)
                dist.append(_get(frame, "distance"))
    return {"time": times, "heartrate": hr, "velocity": vel, "distance": dist}


def parse_fit(path: str, source_id: str, tz, long_threshold: float,
              reclassify_generic: bool = True) -> Iterator[dict]:
    """Yield one entry per `session` message in a .fit file."""
    with fitdecode.FitReader(path) as fr:
        for frame in fr:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "session":
                entry = session_to_entry(frame, source_id, tz, long_threshold, reclassify_generic)
                if entry is not None:
                    yield entry


# ---------------------------------------------------------------------------
# Input expansion (files / dirs / zips)
# ---------------------------------------------------------------------------

def iter_fit_paths(paths) -> Iterator[Tuple[str, str]]:
    """Yield (fit_path, source_id) from files, directories, and .zip archives.

    .zip archives are extracted to a temp dir; their inner .fit files are processed.
    source_id is the .fit filename stem (the COROS activity id).
    """
    for p in paths:
        if os.path.isdir(p):
            inner = sorted(glob.glob(os.path.join(p, "**", "*.fit"), recursive=True))
            zips = sorted(glob.glob(os.path.join(p, "**", "*.zip"), recursive=True))
            for fp in inner:
                yield fp, os.path.splitext(os.path.basename(fp))[0]
            yield from _iter_zip_paths(zips)
        elif p.lower().endswith(".zip"):
            yield from _iter_zip_paths([p])
        elif p.lower().endswith(".fit"):
            yield p, os.path.splitext(os.path.basename(p))[0]
        else:
            sys.stderr.write(f"# skip (not .fit/.zip/dir): {p}\n")


def _iter_zip_paths(zips) -> Iterator[Tuple[str, str]]:
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
                if not names:
                    continue
                tmp = tempfile.mkdtemp(prefix="ompb_fit_")
                for n in names:
                    extracted = zf.extract(n, tmp)
                    yield extracted, os.path.splitext(os.path.basename(n))[0]
        except zipfile.BadZipFile:
            sys.stderr.write(f"# skip (bad zip): {zp}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# (de-dup helpers — load_seen / dup_kind / mark_seen — are imported from ompb_env)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import COROS/Garmin .fit activities into OMPB training-log JSONL.")
    ap.add_argument("paths", nargs="+", help=".fit file(s), .zip archive(s), or directory(ies)")
    ap.add_argument("--tz", help="Local timezone (e.g. Asia/Seoul). Default: system local.")
    ap.add_argument("--long-threshold", type=float, default=19.0,
                    help="Running distance (km) at or above which type is 'long' (default 19).")
    ap.add_argument("--dedup-against", help="Existing JSONL log to dedup against (default: the resolved home log).")
    ap.add_argument("--home", help="OMPB_HOME state dir. Default: smart-resolve ($OMPB_HOME -> ~/.ompb -> ./.ompb).")
    ap.add_argument("--stdout", action="store_true", help="Write JSONL to stdout instead of appending to the home log.")
    ap.add_argument("--no-reclassify-generic", dest="reclassify_generic", action="store_false",
                    help="Disable reclassifying COROS 'generic' activities that look like runs into running.")
    ap.add_argument("--quiet", action="store_true", help="Suppress the per-sport summary on stderr.")
    args = ap.parse_args(argv)

    tz = None
    if args.tz:
        if ZoneInfo is None:
            sys.stderr.write("warning: zoneinfo unavailable; using system local time.\n")
        else:
            try:
                tz = ZoneInfo(args.tz)
            except Exception:
                sys.stderr.write(f"warning: unknown timezone {args.tz!r}; using system local time.\n")

    home = resolve_home(args.home, create=True)
    target = log_path(home)
    seen = load_seen(args.dedup_against or target)
    by_type = {}
    by_sport = {}
    emitted = files_seen = skipped_dupe = xsrc = errored = reclassified = 0

    sink = sys.stdout if args.stdout else open(target, "a", encoding="utf-8")
    try:
        for fit_path, source_id in iter_fit_paths(args.paths):
            files_seen += 1
            if source_id in seen["ids"]:
                skipped_dupe += 1
                continue
            try:
                for entry in parse_fit(fit_path, source_id, tz, args.long_threshold, args.reclassify_generic):
                    dk = dup_kind(seen, entry)
                    if dk:
                        skipped_dupe += 1
                        if dk == "cross-source":
                            xsrc += 1
                        continue
                    line = json.dumps(entry, ensure_ascii=False)
                    json.loads(line)  # integrity guard: never write a line that won't parse back
                    mark_seen(seen, entry)
                    sink.write(line + "\n")
                    emitted += 1
                    by_type[entry["type"]] = by_type.get(entry["type"], 0) + 1
                    by_sport[entry["sport"]] = by_sport.get(entry["sport"], 0) + 1
                    if entry.get("reclassified_from_sport"):
                        reclassified += 1
            except Exception as e:
                errored += 1
                sys.stderr.write(f"# error parsing {os.path.basename(fit_path)}: {e}\n")
    finally:
        if sink is not sys.stdout:
            sink.close()

    if not args.quiet:
        sys.stderr.write(
            f"# import_fit.py: {files_seen} files, {emitted} activities emitted, "
            f"{skipped_dupe} duplicates skipped, {errored} errored.\n"
        )
        if xsrc:
            sys.stderr.write(f"#   of those, {xsrc} were cross-source (same activity already imported from another source)\n")
        if not args.stdout:
            sys.stderr.write(f"#   appended to: {target}\n")
        if reclassified:
            sys.stderr.write(f"#   reclassified generic -> running: {reclassified}\n")
        if by_type:
            sys.stderr.write("#   by type:  " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())) + "\n")
        if by_sport:
            sys.stderr.write("#   by sport: " + ", ".join(f"{k}={v}" for k, v in sorted(by_sport.items())) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
