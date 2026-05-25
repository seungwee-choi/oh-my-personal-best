#!/usr/bin/env python3
"""
build_week.py — Render the weekly training-plan card from a plan-week.json (stdlib only).

The week's prescription is produced by session-coach / race-plan and stored at
$OMPB_HOME/plan-week.json (the PLAN_DATA contract: athlete, goal, week, days[], coach_notes).
This script injects it into a vendored self-contained HTML template (card layout, print-ready)
and writes $OMPB_HOME/weeks/week-<date>.html. It does NOT design the plan — it renders what
session-coach wrote. No external dependencies.

Usage:
  python3 build_week.py [--home DIR] [--lang en|ko] [--plan PATH] [--out PATH]
"""

import argparse
import datetime as dt
import json
import os
import sys

from ompb_env import resolve_home, resolve_lang

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")
_QUALITY = {"interval", "tempo"}
_EASYISH = {"easy", "long", "recovery", "cross"}


def compute_summary(days):
    total = round(sum((d.get("distance_km") or 0) for d in days), 1)
    longs = [d.get("distance_km") or 0 for d in days if d.get("type") == "long"]
    return {
        "total_km": total,
        "sessions": sum(1 for d in days if d.get("type") != "rest"),
        "quality": sum(1 for d in days if d.get("type") in _QUALITY),
        "long_km": round(max(longs), 1) if longs else 0,
        "rest_days": sum(1 for d in days if d.get("type") == "rest"),
        "intensity_split": {
            "easy_km": round(sum((d.get("distance_km") or 0) for d in days if d.get("type") in _EASYISH), 1),
            "quality_km": round(sum((d.get("distance_km") or 0) for d in days if d.get("type") in _QUALITY), 1),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the OMPB weekly training-plan card.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--lang", choices=["en", "ko"], help="Language (default: config.json language, else en).")
    ap.add_argument("--plan", help="plan-week.json path (default: <home>/plan-week.json).")
    ap.add_argument("--out", help="Output HTML path (default: <home>/weeks/week-<date>.html).")
    args = ap.parse_args(argv)

    home = resolve_home(args.home)
    args.lang = resolve_lang(args.lang, home)
    plan_path = args.plan or os.path.join(home, "plan-week.json")
    if not os.path.exists(plan_path):
        sys.stderr.write(f"error: no weekly plan at {plan_path}. Build one with /pb-plan "
                         "(race-plan) or /pb-week, then render.\n")
        return 2

    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    days = plan.get("days") or []
    if not days:
        sys.stderr.write("error: plan-week.json has no days[].\n")
        return 2

    # keep "today" current; fill summary if session-coach didn't include one
    plan.setdefault("today", dt.date.today().isoformat())
    if "summary" not in plan:
        plan["summary"] = compute_summary(days)

    tmpl_name = "week.ko.html" if args.lang == "ko" else "week.html"
    tmpl_path = os.path.join(TEMPLATES, tmpl_name)
    if not os.path.exists(tmpl_path):
        sys.stderr.write(f"error: template not found: {tmpl_path}\n")
        return 2
    template = open(tmpl_path, encoding="utf-8").read()
    if "__PLAN_DATA__" not in template:
        sys.stderr.write("error: template missing __PLAN_DATA__ placeholder.\n")
        return 2
    html = template.replace("__PLAN_DATA__", json.dumps(plan, ensure_ascii=False))

    out = args.out or os.path.join(home, "weeks", f"week-{dt.date.today().isoformat()}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    wk = plan.get("week", {})
    sys.stderr.write(f"# build_week.py: week {wk.get('plan_week','?')}/{wk.get('total_weeks','?')} "
                     f"({plan['summary']['total_km']} km, {plan['summary']['quality']} quality) -> {out}\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
