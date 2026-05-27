#!/usr/bin/env python3
"""build_activity.py — render a single-activity analysis card (stdlib; fitdecode for .fit).

Gathers ONE activity's laps + per-second streams (via the .fit / Strava adapters), runs the
analysis engine (analyze.py: structure/reps/pacing + decoupling/zones/hard-efforts/GAP), and
injects the result into a vendored self-contained HTML card (inline SVG, print-ready) — the
session-level companion to build_week (this week) and build_report (the whole block).

Single activity only — never bulk (Strava rate limits).

Usage:
  python3 build_activity.py (--fit PATH | --strava ID) [--home DIR] [--lang en|ko]
                            [--out PATH] [--no-streams]
"""
import argparse
import datetime as dt
import json
import os
import sys

from ompb_env import resolve_home, resolve_lang, log_path, star_cta
import analyze

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


def _hrmax(home):
    try:
        import classify
        with open(log_path(home), encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
        return classify.calibrate(entries).get("hrmax")
    except Exception:  # noqa: BLE001 — zones are best-effort
        return None


def _gather(args, home):
    """Return (laps, total_km, streams, date, source) for the requested activity."""
    if args.fit:
        from import_fit import laps_from_fit, streams_from_fit, parse_fit
        stem = os.path.splitext(os.path.basename(args.fit))[0]
        sess = next(iter(parse_fit(args.fit, stem, None, args.long_threshold)), None)
        laps, total = laps_from_fit(args.fit)
        streams = {} if args.no_streams else streams_from_fit(args.fit)
        return laps, total, streams, (sess or {}).get("date"), "fit"
    from import_strava import fetch_detail, _laps_from_detail, _meta_from_detail, laps_from_strava_streams
    detail = fetch_detail(args.strava, home)
    laps, total = _laps_from_detail(detail)
    streams = {}
    if not args.no_streams:
        try:
            streams = laps_from_strava_streams(args.strava, home)
        except Exception:  # noqa: BLE001 — streams optional
            streams = {}
    return laps, total, streams, _meta_from_detail(detail).get("date"), "strava"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a single-activity analysis card.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fit", help="Path to a .fit file (offline).")
    src.add_argument("--strava", help="Strava activity id (or 'strava-<id>'); needs strava.json.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--lang", choices=["en", "ko"], help="Language (default: config.json, else en).")
    ap.add_argument("--out", help="Output HTML (default: <home>/activities/activity-<date>.html).")
    ap.add_argument("--long-threshold", type=float, default=19.0)
    ap.add_argument("--no-streams", action="store_true")
    args = ap.parse_args(argv)

    home = resolve_home(args.home)
    args.lang = resolve_lang(args.lang, home)

    try:
        laps, total, streams, date, source = _gather(args, home)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"error: {e}\n")
        return 1
    if not laps:
        sys.stderr.write("error: no laps found for this activity (treadmill/manual?).\n")
        return 2

    data = analyze.analyze_laps(laps, distance_km=total, long_km=args.long_threshold)
    if streams:
        try:
            data.update(analyze.analyze_streams(streams, hrmax=_hrmax(home)))
        except Exception:  # noqa: BLE001
            pass
    data["date"] = date
    data["source"] = source

    tmpl_path = os.path.join(TEMPLATES, "activity.ko.html" if args.lang == "ko" else "activity.html")
    if not os.path.exists(tmpl_path):
        sys.stderr.write(f"error: template not found: {tmpl_path}\n")
        return 2
    template = open(tmpl_path, encoding="utf-8").read()
    if "__ACTIVITY_DATA__" not in template:
        sys.stderr.write("error: template missing __ACTIVITY_DATA__ placeholder.\n")
        return 2
    html = template.replace("__ACTIVITY_DATA__", json.dumps(data, ensure_ascii=False))

    stamp = date or dt.date.today().isoformat()
    out = args.out or os.path.join(home, "activities", f"activity-{stamp}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    sys.stderr.write(f"# build_activity.py: {data.get('structure')} "
                     f"({(data.get('summary') or {}).get('distance_km')} km) -> {out}\n")
    star_cta(home, args.lang)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
