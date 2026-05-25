#!/usr/bin/env python3
"""
build_report.py — Render the comprehensive athlete report from OMPB state (stdlib only).

Reads $OMPB_HOME state (training-log.jsonl + runner-profile.json + pb-history.json +
diagnosis.json), assembles the `REPORT_DATA` object that the report template consumes, injects
it into a vendored self-contained HTML template (designed offline, inline SVG, print/PDF-ready),
and writes the result to $OMPB_HOME/reports/report-<date>.html. No external dependencies.

The template lives at <plugin>/templates/report.html (English) or report.ko.html (Korean) and
contains a single `const REPORT_DATA = __REPORT_DATA__;` placeholder that this script fills.

Usage:
  python3 build_report.py [--home DIR] [--lang en|ko] [--out PATH]
"""

import argparse
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date

from ompb_env import resolve_home, resolve_lang

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


def load_log(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def pace_to_sec(p):
    if not p or ":" not in str(p):
        return None
    try:
        m, s = str(p).split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return None


def fp(x):
    return f"{int(x) // 60}:{int(x) % 60:02d}" if x else None


def build_report_data(home):
    rows = load_log(os.path.join(home, "training-log.jsonl"))
    runs = [r for r in rows if r.get("sport") == "running"]
    if not rows:
        raise SystemExit("error: training log is empty — import data first (/pb-log).")
    prof = load_json(os.path.join(home, "runner-profile.json")) or {}
    pbh = load_json(os.path.join(home, "pb-history.json")) or {"entries": []}
    diag = load_json(os.path.join(home, "diagnosis.json")) or {
        "summary": "", "limiter": "", "observations": []}

    def D(r):
        return (r.get("actual") or {}).get("distance_km") or 0

    dates = sorted(r["date"] for r in rows if r.get("date"))
    first, last = dates[0], dates[-1]
    weeks = max(1, round((date.fromisoformat(last) - date.fromisoformat(first)).days / 7))
    run_km = round(sum(D(r) for r in runs))
    cross_km = round(sum(D(r) for r in rows if r.get("sport") != "running"))

    # monthly
    mvol = defaultdict(float); mp = defaultdict(list); mh = defaultdict(list)
    ml = defaultdict(float); mc = defaultdict(int)
    for r in runs:
        m = r["date"][:7]; a = r.get("actual") or {}
        mvol[m] += D(r); mc[m] += 1; ml[m] = max(ml[m], D(r))
        if pace_to_sec(a.get("pace")):
            mp[m].append(pace_to_sec(a.get("pace")))
        if a.get("avg_hr"):
            mh[m].append(a["avg_hr"])
    monthly = [{"month": m, "runs": mc[m], "km": round(mvol[m]),
                "avg_pace": fp(sum(mp[m]) / len(mp[m]) if mp[m] else 0),
                "avg_hr": round(sum(mh[m]) / len(mh[m])) if mh[m] else None,
                "longest_km": round(ml[m], 1)} for m in sorted(mvol)]

    # hr by pace (30s bins, keep bins with >=8 samples)
    band = defaultdict(list)
    for r in runs:
        a = r.get("actual") or {}
        p, h = pace_to_sec(a.get("pace")), a.get("avg_hr")
        if p and h:
            band[p // 30].append((p, h))
    hr_by_pace = [{"pace": fp(sum(x[0] for x in v) / len(v)),
                   "avg_hr": round(sum(x[1] for x in v) / len(v)), "n": len(v)}
                  for k, v in sorted(band.items()) if len(v) >= 8]

    # intensity by HR zone (easy<140, moderate 140-154, hard>=155)
    hrs = [(r.get("actual") or {}).get("avg_hr") for r in runs]
    hrs = [h for h in hrs if h]
    tot = len(hrs) or 1
    by_hr = {"easy": round(sum(h < 140 for h in hrs) / tot, 2),
             "moderate": round(sum(140 <= h < 155 for h in hrs) / tot, 2),
             "hard": round(sum(h >= 155 for h in hrs) / tot, 2)}

    # recent 10 weeks
    wk = defaultdict(float)
    for r in runs:
        y, w, _ = date.fromisoformat(r["date"]).isocalendar(); wk[(y, w)] += D(r)
    recent = [round(wk[k]) for k in sorted(wk)[-10:]]

    return {
        "athlete": {"label": prof.get("name") or "athlete", "experience": prof.get("experience"),
                    "weekly_mileage_km": prof.get("weekly_mileage_km"),
                    "current_pb": prof.get("current_pb", {})},
        "window": {"first": first, "last": last, "weeks": weeks},
        "totals": {"activities": len(rows), "runs": len(runs), "run_km": run_km,
                   "cross_km": cross_km, "avg_weekly_run_km": round(run_km / weeks)},
        "pbs": [{"event": e.get("event"), "time": e.get("time"), "date": e.get("date")}
                for e in pbh.get("entries", [])],
        "intensity_mix": dict(Counter(r.get("type") for r in rows)),
        "intensity_by_hr": by_hr,
        "monthly": monthly,
        "hr_by_pace": hr_by_pace,
        "recent_weeks_km": recent,
        "diagnosis": {"summary": diag.get("summary", ""), "limiter": diag.get("limiter", ""),
                      "observations": diag.get("observations", [])},
        "_has_diagnosis": bool(diag.get("summary")),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the OMPB athlete report from state.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--lang", choices=["en", "ko"], help="Language (default: config.json language, else en).")
    ap.add_argument("--out", help="Output HTML path (default: <home>/reports/report-<date>.html).")
    args = ap.parse_args(argv)

    home = resolve_home(args.home)
    args.lang = resolve_lang(args.lang, home)
    log = os.path.join(home, "training-log.jsonl")
    if not os.path.exists(log):
        sys.stderr.write(f"error: no training log at {log}. Run /pb-setup or /pb-log first.\n")
        return 2

    tmpl_name = "report.ko.html" if args.lang == "ko" else "report.html"
    tmpl_path = os.path.join(TEMPLATES, tmpl_name)
    if not os.path.exists(tmpl_path):
        sys.stderr.write(f"error: template not found: {tmpl_path}\n")
        return 2

    data = build_report_data(home)
    has_diag = data.pop("_has_diagnosis")
    template = open(tmpl_path, encoding="utf-8").read()
    if "__REPORT_DATA__" not in template:
        sys.stderr.write("error: template missing __REPORT_DATA__ placeholder.\n")
        return 2
    html = template.replace("__REPORT_DATA__", json.dumps(data, ensure_ascii=False))

    out = args.out or os.path.join(home, "reports", f"report-{dt.date.today().isoformat()}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    sys.stderr.write(f"# build_report.py: report ({args.lang}) from {data['totals']['activities']} "
                     f"activities -> {out}\n")
    if not has_diag:
        sys.stderr.write("#   note: no diagnosis.json — run race-analyst (or /pb-deck) first for "
                         "the summary/limiter/findings sections.\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
