#!/usr/bin/env python3
"""reclassify.py — re-type running sessions in the training log with the calibrated,
runner-relative classifier (standard library only).

Device imports type runs easy/long by distance alone. This pass calibrates HR/pace
bands from the whole log (see classify.py) and relabels each run into
recovery / easy / tempo / interval / long, so the intensity distribution reflects
what the runner actually did. Safe to re-run; calibration improves as the log grows.

What it touches: only running sessions currently typed easy/long/tempo/interval/recovery.
It never changes race / cross / rest, and never overrides a type that came from an
explicit activity name (entries marked ``type_source: "name"``).

Usage:
  python3 reclassify.py [--home DIR] [--long-threshold KM] [--dry-run]
"""
import argparse
import json
import sys
from collections import Counter

from ompb_env import resolve_home, log_path
import classify

_REFINABLE = set(classify.RUN_TYPES)  # easy/long/tempo/interval/recovery/progression


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-type runs with the calibrated classifier.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--long-threshold", type=float, default=19.0)
    ap.add_argument("--dry-run", action="store_true", help="Report the change without writing.")
    args = ap.parse_args(argv)

    home = resolve_home(args.home)
    path = log_path(home)
    try:
        with open(path, encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        sys.stderr.write(f"error: no training log at {path} — import data first.\n")
        return 2

    ref = classify.calibrate(entries)

    before, after = Counter(), Counter()
    changed = 0
    for e in entries:
        if e.get("sport") not in (None, "running"):
            continue
        cur = e.get("type")
        # Skip coarse-uncategorizable types and anything a stronger source already settled:
        # a user correction ("user", authoritative ground truth), the runner/importer name
        # ("name"), Strava's workout_type ("strava"), or the lap-structure engine ("laps"). The
        # aggregate pass here has NO per-lap data, so it must never overwrite those with a guess.
        if cur not in _REFINABLE or e.get("type_source") in ("name", "strava", "laps", "user"):
            continue
        a = e.get("actual") or {}
        dist = a.get("distance_km")
        before[cur] += 1
        new = classify.refine(a, dist, ref, long_km=args.long_threshold)
        after[new] += 1
        if new != cur:
            e["type"] = new
            changed += 1

    # Report
    hrmax = ref.get("hrmax")
    sys.stderr.write(
        f"# reclassify: {changed} of {sum(before.values())} runs re-typed"
        + (f" (HRmax≈{hrmax}, HR-calibrated)" if hrmax else " (pace-only; no HR data)") + ".\n")
    order = ["recovery", "easy", "tempo", "interval", "progression", "long"]
    sys.stderr.write("#   before: " + ", ".join(f"{k}={before[k]}" for k in order if before[k]) + "\n")
    sys.stderr.write("#   after:  " + ", ".join(f"{k}={after[k]}" for k in order if after[k]) + "\n")

    if args.dry_run:
        sys.stderr.write("#   (dry run — no changes written)\n")
        return 0

    if changed:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        import os
        os.replace(tmp, path)  # atomic
        sys.stderr.write(f"#   wrote {path}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
