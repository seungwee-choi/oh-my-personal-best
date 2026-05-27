#!/usr/bin/env python3
"""analyze_activity.py — on-demand deep analysis of ONE activity from its laps.

Single-activity only (never bulk — Strava rate limits). Fetches per-lap data from the
right source, then runs the source-agnostic engine (analyze.py): workout structure
(interval / tempo / progression / steady), rep detection, and pacing quality. Prints
the analysis as JSON.

  - .fit file:  python3 analyze_activity.py --fit run.fit          (offline, no creds)
  - Strava:     python3 analyze_activity.py --strava 12345 [--home DIR]   (1 API call)

Use it to upgrade a coarse/heuristic type to a high-confidence one (interval with reps,
or a confirmed tempo) — surfaces call ompb_core.analyze_activity.
"""
import argparse
import json
import sys

import analyze


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep-analyze a single activity's lap structure.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fit", help="Path to a .fit file (offline).")
    src.add_argument("--strava", help="Strava activity id (or 'strava-<id>'); needs strava.json.")
    ap.add_argument("--home", help="OMPB_HOME (for Strava credentials).")
    ap.add_argument("--long-threshold", type=float, default=19.0)
    args = ap.parse_args(argv)

    try:
        if args.fit:
            from import_fit import laps_from_fit  # lazy: only .fit needs fitdecode
            laps, total_km = laps_from_fit(args.fit)
        else:
            from import_strava import laps_from_strava
            laps, total_km = laps_from_strava(args.strava, args.home)
    except Exception as e:  # noqa: BLE001 — surface a clean message, not a traceback
        sys.stderr.write(f"error: {e}\n")
        return 1

    result = analyze.analyze_laps(laps, distance_km=total_km, long_km=args.long_threshold)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
