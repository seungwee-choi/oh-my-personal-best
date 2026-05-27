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


def _hrmax_from_log(home):
    """The runner's calibrated HRmax (for time-in-zone / hard-effort zones), or None."""
    try:
        from ompb_env import resolve_home, log_path
        import classify
        with open(log_path(resolve_home(home)), encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
        return classify.calibrate(entries).get("hrmax")
    except Exception:  # noqa: BLE001 — zones are best-effort
        return None


def _corroborate(result):
    """Cross-check lap structure against the stream-derived hard-effort count."""
    eff = result.get("hard_efforts")
    if eff is None:
        return
    if result["structure"] == "interval" and result.get("reps"):
        if abs(eff - len(result["reps"])) <= 1:
            result["confidence"] = "high"
            result["notes"].append(f"stream-confirmed: {eff} hard efforts")
        else:
            result["notes"].append(f"stream shows {eff} hard efforts vs {len(result['reps'])} lap reps")
    elif result["structure"] in ("tempo", "steady", "unknown") and eff >= 3:
        result["notes"].append(f"stream shows {eff} sustained hard efforts — possible intervals")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep-analyze a single activity (laps + streams).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fit", help="Path to a .fit file (offline).")
    src.add_argument("--strava", help="Strava activity id (or 'strava-<id>'); needs strava.json.")
    ap.add_argument("--home", help="OMPB_HOME (Strava credentials + HRmax calibration).")
    ap.add_argument("--long-threshold", type=float, default=19.0)
    ap.add_argument("--no-streams", action="store_true", help="Skip the per-second stream pass.")
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

    # Per-second streams: decoupling, time-in-zone, hard-effort count (1 extra Strava call).
    if not args.no_streams:
        try:
            if args.fit:
                from import_fit import streams_from_fit
                streams = streams_from_fit(args.fit)
            else:
                from import_strava import laps_from_strava_streams
                streams = laps_from_strava_streams(args.strava, args.home)
            result.update(analyze.analyze_streams(streams, hrmax=_hrmax_from_log(args.home)))
            _corroborate(result)
        except Exception as e:  # noqa: BLE001 — streams are best-effort; laps already stand
            result["notes"].append(f"streams unavailable: {e}")

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
