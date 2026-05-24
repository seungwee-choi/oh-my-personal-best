#!/usr/bin/env python3
"""
build_deck.py — Render OMPB analysis results as a single self-contained HTML slide deck.

Reads `.ompb/training-log.jsonl` (and, when present, `diagnosis.json`, `goal.json`,
`pb-history.json`, `plan-state.json`) and emits one portable `.html` file with inline
SVG charts — no external JS, no CDN, no server. Open it in a browser, screenshot it,
or share the file.

Charts are drawn as inline SVG by hand (standard library only), so the deck renders
offline and deterministically. A tiny inline script handles slide navigation only.

Slides degrade gracefully: the diagnosis / PB / next-block slides appear only when their
source files exist; otherwise the deck shows pure data visualization.

Usage:
    python3 build_deck.py
    python3 build_deck.py --log .ompb/training-log.jsonl --out .ompb/decks/deck.html
    python3 build_deck.py --tz Asia/Seoul --title "My 2025 Season"

Inputs (auto-discovered in the log's directory unless overridden):
    --log         training-log.jsonl                 (required; the activity log)
    --diagnosis   diagnosis.json   {summary, limiter, feasibility, observations[]}
    --goal        goal.json        {event, target_time, race_date, ...}
    --pb          pb-history.json  {entries:[{event,time,date,race_name}]}
    --plan        plan-state.json  {phase, plan_week, total_weeks, key_sessions[], ...}
    --out         output html path (default: <logdir>/decks/deck-<YYYY-MM-DD>.html)
    --title       deck title (default: "Training Analysis")
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import sys
from collections import Counter, defaultdict
from ompb_env import resolve_home, log_path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Palette (dark deck)
# ---------------------------------------------------------------------------
BG = "#0d1117"
CARD = "#161b22"
INK = "#e6edf3"
MUTED = "#8b949e"
GRID = "#30363d"
RUN = "#f97316"   # orange — running
CROSS = "#3b82f6"  # blue — cross-training
LONG = "#22c55e"  # green — long runs
HR = "#ef4444"    # red — heart rate


# ---------------------------------------------------------------------------
# Load + aggregate
# ---------------------------------------------------------------------------

def load_log(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_json(path: Optional[str]) -> Optional[dict]:
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def pace_to_sec(p: Optional[str]) -> Optional[int]:
    if not p or ":" not in str(p):
        return None
    try:
        m, s = str(p).split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return None


def sec_to_pace(sec: Optional[float]) -> str:
    if not sec or sec <= 0:
        return "–"
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def month_key(date_str: str) -> Optional[str]:
    return date_str[:7] if date_str and len(date_str) >= 7 else None


def month_range(first: str, last: str) -> List[str]:
    """Inclusive list of YYYY-MM keys from first to last (fills empty months)."""
    fy, fm = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    y, m = fy, fm
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def aggregate(rows: List[dict]) -> dict:
    runs = [r for r in rows if r.get("sport") == "running"]
    dates = sorted(r["date"] for r in rows if r.get("date"))
    first, last = (dates[0], dates[-1]) if dates else ("", "")

    def dist(r):
        return (r.get("actual") or {}).get("distance_km") or 0.0

    total_km = sum(dist(r) for r in rows)
    run_km = sum(dist(r) for r in runs)
    cross_km = total_km - run_km

    months = month_range(first, last) if first else []
    run_by_m = {m: 0.0 for m in months}
    cross_by_m = {m: 0.0 for m in months}
    pace_by_m: Dict[str, List[int]] = defaultdict(list)
    hr_by_m: Dict[str, List[int]] = defaultdict(list)
    longest_by_m = {m: 0.0 for m in months}
    for r in rows:
        mk = month_key(r.get("date", ""))
        if mk is None or mk not in run_by_m:
            continue
        if r.get("sport") == "running":
            run_by_m[mk] += dist(r)
            longest_by_m[mk] = max(longest_by_m[mk], dist(r))
            ps = pace_to_sec((r.get("actual") or {}).get("pace"))
            if ps:
                pace_by_m[mk].append(ps)
            hr = (r.get("actual") or {}).get("avg_hr")
            if hr:
                hr_by_m[mk].append(int(hr))
        else:
            cross_by_m[mk] += dist(r)

    type_counts = Counter(r.get("type", "?") for r in rows)
    hr_pace = []
    for r in runs:
        a = r.get("actual") or {}
        ps, hr = pace_to_sec(a.get("pace")), a.get("avg_hr")
        if ps and hr:
            hr_pace.append((ps, int(hr)))

    weeks = max(1, round((dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days / 7)) if first else 1

    return {
        "first": first, "last": last, "weeks": weeks,
        "n_activities": len(rows), "n_runs": len(runs),
        "total_km": total_km, "run_km": run_km, "cross_km": cross_km,
        "avg_weekly_km": run_km / weeks,
        "months": months,
        "run_by_m": run_by_m, "cross_by_m": cross_by_m,
        "pace_by_m": {m: (sum(v) / len(v)) for m, v in pace_by_m.items()},
        "hr_by_m": {m: (sum(v) / len(v)) for m, v in hr_by_m.items()},
        "longest_by_m": longest_by_m,
        "type_counts": type_counts,
        "hr_pace": hr_pace,
    }


# ---------------------------------------------------------------------------
# SVG chart primitives  (viewBox 960x440, scaled to 100% width via CSS)
# ---------------------------------------------------------------------------
W, H = 960, 440
PADL, PADR, PADT, PADB = 64, 24, 28, 64


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(v))
    for f in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if f * mag >= v:
            return f * mag
    return 10 * mag


def _mlabel(m: str) -> str:
    return dt.date(int(m[:4]), int(m[5:7]), 1).strftime("%b'%y")


def _axes(ymax: float, ylabel: str, n_y: int = 4) -> str:
    px = []
    for i in range(n_y + 1):
        y = PADT + (H - PADT - PADB) * i / n_y
        val = ymax * (n_y - i) / n_y
        px.append(f'<line x1="{PADL}" y1="{y:.1f}" x2="{W-PADR}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        px.append(f'<text x="{PADL-8}" y="{y+4:.1f}" fill="{MUTED}" font-size="12" text-anchor="end">{val:.0f}</text>')
    px.append(f'<text x="16" y="{PADT-10}" fill="{MUTED}" font-size="12">{ylabel}</text>')
    return "".join(px)


def _xband(months: List[str]) -> Tuple[float, float]:
    span = W - PADL - PADR
    band = span / max(1, len(months))
    return band, span


def chart_volume(agg: dict) -> str:
    months = agg["months"]
    run, cross = agg["run_by_m"], agg["cross_by_m"]
    ymax = _nice_max(max((run[m] + cross[m]) for m in months) if months else 1)
    band, _ = _xband(months)
    bw = band * 0.7
    bars = []
    plot_h = H - PADT - PADB
    for i, m in enumerate(months):
        x = PADL + band * i + (band - bw) / 2
        rk, ck = run[m], cross[m]
        rh = plot_h * rk / ymax
        ch = plot_h * ck / ymax
        y_run = H - PADB - rh
        y_cross = y_run - ch
        bars.append(f'<rect x="{x:.1f}" y="{y_run:.1f}" width="{bw:.1f}" height="{rh:.1f}" fill="{RUN}"/>')
        if ck > 0:
            bars.append(f'<rect x="{x:.1f}" y="{y_cross:.1f}" width="{bw:.1f}" height="{ch:.1f}" fill="{CROSS}"/>')
        if i % 2 == 0 or len(months) <= 14:
            bars.append(f'<text x="{x+bw/2:.1f}" y="{H-PADB+18}" fill="{MUTED}" font-size="11" text-anchor="middle">{_mlabel(m)}</text>')
    legend = (f'<rect x="{W-PADR-180}" y="8" width="12" height="12" fill="{RUN}"/>'
              f'<text x="{W-PADR-162}" y="19" fill="{INK}" font-size="12">running km</text>'
              f'<rect x="{W-PADR-80}" y="8" width="12" height="12" fill="{CROSS}"/>'
              f'<text x="{W-PADR-62}" y="19" fill="{INK}" font-size="12">cross km</text>')
    return _svg(_axes(ymax, "km / month") + "".join(bars) + legend)


def chart_line(agg: dict, key: str, label: str, color: str, fmt_pace: bool = False) -> str:
    months = agg["months"]
    data = agg[key]
    vals = [(i, data[m]) for i, m in enumerate(months) if m in data and data[m]]
    if not vals:
        return _svg(f'<text x="{W/2}" y="{H/2}" fill="{MUTED}" font-size="16" text-anchor="middle">no data</text>')
    ys = [v for _, v in vals]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.15 or hi * 0.1 or 1
    ymin, ymax = lo - pad, hi + pad
    band, _ = _xband(months)
    plot_h = H - PADT - PADB

    def py(v):
        return H - PADB - plot_h * (v - ymin) / (ymax - ymin)

    def px(i):
        return PADL + band * i + band / 2

    # y axis labels
    ax = []
    for k in range(5):
        yy = PADT + plot_h * k / 4
        vv = ymax - (ymax - ymin) * k / 4
        ax.append(f'<line x1="{PADL}" y1="{yy:.1f}" x2="{W-PADR}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        lab = sec_to_pace(vv) if fmt_pace else f"{vv:.0f}"
        ax.append(f'<text x="{PADL-8}" y="{yy+4:.1f}" fill="{MUTED}" font-size="12" text-anchor="end">{lab}</text>')
    ax.append(f'<text x="16" y="{PADT-10}" fill="{MUTED}" font-size="12">{label}</text>')
    if fmt_pace:
        ax.append(f'<text x="{W-PADR}" y="{PADT-10}" fill="{MUTED}" font-size="11" text-anchor="end">lower = faster</text>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in vals)
    dots = "".join(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="3.5" fill="{color}"/>' for i, v in vals)
    xlab = []
    for i, m in enumerate(months):
        if i % 2 == 0 or len(months) <= 14:
            xlab.append(f'<text x="{px(i):.1f}" y="{H-PADB+18}" fill="{MUTED}" font-size="11" text-anchor="middle">{_mlabel(m)}</text>')
    line = f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>'
    return _svg("".join(ax) + line + dots + "".join(xlab))


def chart_donut(agg: dict) -> str:
    counts = agg["type_counts"]
    palette = {"easy": RUN, "long": LONG, "tempo": "#eab308", "interval": "#a855f7",
               "recovery": "#14b8a6", "race": "#ef4444", "cross": CROSS, "rest": MUTED}
    items = [(k, v) for k, v in counts.most_common() if v]
    total = sum(v for _, v in items) or 1
    cx, cy, r, rin = 300, H / 2, 150, 84
    segs, legend = [], []
    a0 = -math.pi / 2
    for idx, (k, v) in enumerate(items):
        frac = v / total
        a1 = a0 + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        col = palette.get(k, MUTED)
        segs.append(f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 {large} 1 {x1:.1f} {y1:.1f} L {cx} {cy} Z" fill="{col}"/>')
        ly = 70 + idx * 34
        legend.append(f'<rect x="600" y="{ly}" width="14" height="14" rx="3" fill="{col}"/>'
                      f'<text x="624" y="{ly+12}" fill="{INK}" font-size="15">{html.escape(k)} · {v} ({frac*100:.0f}%)</text>')
        a0 = a1
    hole = f'<circle cx="{cx}" cy="{cy}" r="{rin}" fill="{BG}"/>'
    center = (f'<text x="{cx}" y="{cy-4}" fill="{INK}" font-size="30" font-weight="700" text-anchor="middle">{total}</text>'
              f'<text x="{cx}" y="{cy+20}" fill="{MUTED}" font-size="14" text-anchor="middle">activities</text>')
    return _svg("".join(segs) + hole + center + "".join(legend))


def chart_scatter(agg: dict) -> str:
    pts = agg["hr_pace"]
    if not pts:
        return _svg(f'<text x="{W/2}" y="{H/2}" fill="{MUTED}" font-size="16" text-anchor="middle">no HR data</text>')
    paces = [p for p, _ in pts]
    hrs = [h for _, h in pts]
    pmin, pmax = min(paces), max(paces)
    hmin, hmax = min(hrs), max(hrs)
    pmin -= 10; pmax += 10; hmin -= 5; hmax += 5
    plot_h = H - PADT - PADB

    def px(p):
        return PADL + (W - PADL - PADR) * (p - pmin) / (pmax - pmin)

    def py(h):
        return H - PADB - plot_h * (h - hmin) / (hmax - hmin)

    ax = []
    for k in range(5):
        yy = PADT + plot_h * k / 4
        vv = hmax - (hmax - hmin) * k / 4
        ax.append(f'<line x1="{PADL}" y1="{yy:.1f}" x2="{W-PADR}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        ax.append(f'<text x="{PADL-8}" y="{yy+4:.1f}" fill="{MUTED}" font-size="12" text-anchor="end">{vv:.0f}</text>')
    for k in range(5):
        pv = pmin + (pmax - pmin) * k / 4
        xx = px(pv)
        ax.append(f'<text x="{xx:.1f}" y="{H-PADB+18}" fill="{MUTED}" font-size="11" text-anchor="middle">{sec_to_pace(pv)}</text>')
    ax.append(f'<text x="16" y="{PADT-10}" fill="{MUTED}" font-size="12">avg HR (bpm)</text>')
    ax.append(f'<text x="{W-PADR}" y="{H-PADB+40}" fill="{MUTED}" font-size="12" text-anchor="end">pace (min/km) — left = faster · lower-left = more efficient</text>')
    dots = "".join(f'<circle cx="{px(p):.1f}" cy="{py(h):.1f}" r="3" fill="{RUN}" opacity="0.45"/>' for p, h in pts)
    return _svg("".join(ax) + dots)


def _svg(inner: str) -> str:
    return f'<svg viewBox="0 0 {W} {H}" class="chart" xmlns="http://www.w3.org/2000/svg" role="img">{inner}</svg>'


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def _stat(label: str, value: str, color: str = INK) -> str:
    return (f'<div class="stat"><div class="stat-v" style="color:{color}">{value}</div>'
            f'<div class="stat-l">{label}</div></div>')


def build_slides(agg: dict, diagnosis: Optional[dict], goal: Optional[dict],
                 pb: Optional[dict], plan: Optional[dict]) -> List[Tuple[str, str]]:
    slides: List[Tuple[str, str]] = []

    # 1. Cover
    span = f'{agg["first"]} → {agg["last"]}'
    cover = (f'<div class="cover"><div class="eyebrow">Training Analysis</div>'
             f'<h1>{agg["n_activities"]} activities over {agg["weeks"]} weeks</h1>'
             f'<div class="span">{span}</div>'
             f'<div class="stats">'
             + _stat("total distance", f'{agg["total_km"]:,.0f} km')
             + _stat("runs", f'{agg["n_runs"]}', RUN)
             + _stat("running distance", f'{agg["run_km"]:,.0f} km', RUN)
             + _stat("avg weekly", f'{agg["avg_weekly_km"]:.0f} km/wk')
             + _stat("cross-training", f'{agg["cross_km"]:,.0f} km', CROSS)
             + '</div></div>')
    slides.append(("", cover))

    slides.append(("Training Volume", chart_volume(agg)))
    slides.append(("Pace Trend", chart_line(agg, "pace_by_m", "avg pace (min/km)", RUN, fmt_pace=True)))
    slides.append(("Training Mix", chart_donut(agg)))
    slides.append(("Aerobic Efficiency", chart_scatter(agg)))
    slides.append(("Heart-Rate Trend", chart_line(agg, "hr_by_m", "avg HR (bpm)", HR)))
    slides.append(("Long-Run Progression", chart_line(agg, "longest_by_m", "longest run (km)", LONG)))

    # PB timeline (optional)
    if pb and pb.get("entries"):
        rows = "".join(
            f'<tr><td>{html.escape(e.get("event",""))}</td><td class="mono">{html.escape(e.get("time",""))}</td>'
            f'<td>{html.escape(e.get("date",""))}</td><td>{html.escape(e.get("race_name",""))}</td></tr>'
            for e in pb["entries"])
        table = (f'<table class="pb"><thead><tr><th>event</th><th>time</th><th>date</th><th>race</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>')
        slides.append(("Personal Bests", table))

    # Diagnosis (optional, from race-analyst) — split across slides so rich content fits.
    if diagnosis:
        head = ['<div class="diag">']
        if diagnosis.get("summary"):
            head.append(f'<p class="lead">{html.escape(diagnosis["summary"])}</p>')
        if diagnosis.get("limiter"):
            head.append(f'<div class="callout"><span class="k">#1 limiter</span> {html.escape(diagnosis["limiter"])}</div>')
        if diagnosis.get("feasibility"):
            head.append(f'<div class="callout"><span class="k">goal feasibility</span> {html.escape(diagnosis["feasibility"])}</div>')
        head.append("</div>")
        slides.append(("Diagnosis", "".join(head)))
        # Observations: paginate (5 per slide) so a long list never overflows a slide.
        obs_list = diagnosis.get("observations", [])
        per = 5
        for i in range(0, len(obs_list), per):
            lis = "".join(f'<li>{html.escape(o)}</li>' for o in obs_list[i:i + per])
            title = "Key Observations" if i == 0 else "Key Observations (cont.)"
            slides.append((title, f'<div class="diag"><ul class="obs">{lis}</ul></div>'))

    # Next block (optional, from plan-state)
    if plan and plan.get("phase"):
        ks = "".join(f"<li>{html.escape(s)}</li>" for s in plan.get("key_sessions", []))
        body = (f'<div class="diag"><div class="callout"><span class="k">current phase</span> '
                f'{html.escape(str(plan.get("phase")))} · week {plan.get("plan_week","?")}/{plan.get("total_weeks","?")}</div>'
                f'<div class="callout"><span class="k">this week target</span> {plan.get("this_week_target_km","?")} km</div>'
                + (f'<p class="lead">Key sessions</p><ul class="obs">{ks}</ul>' if ks else "")
                + '</div>')
        slides.append(("Next Block", body))

    return slides


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

CSS = f"""
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%}}
body{{background:{BG};color:{INK};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;overflow:hidden}}
.deck{{height:100vh;width:100vw;position:relative}}
.slide{{position:absolute;inset:0;display:none;flex-direction:column;padding:48px 64px 72px;opacity:0;transition:opacity .25s}}
.slide.active{{display:flex;opacity:1}}
.slide h2{{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:{MUTED};font-weight:600;margin-bottom:24px}}
.body{{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}}
.chart{{width:100%;height:auto;max-height:78vh}}
.cover{{flex:1;display:flex;flex-direction:column;justify-content:center}}
.eyebrow{{font-size:14px;letter-spacing:.2em;text-transform:uppercase;color:{RUN};font-weight:700;margin-bottom:16px}}
.cover h1{{font-size:54px;line-height:1.05;font-weight:800;letter-spacing:-.02em;max-width:18ch}}
.span{{color:{MUTED};font-size:20px;margin:16px 0 40px}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:760px}}
.stat{{background:{CARD};border:1px solid {GRID};border-radius:14px;padding:20px 22px}}
.stat-v{{font-size:30px;font-weight:800;letter-spacing:-.01em}}
.stat-l{{color:{MUTED};font-size:13px;margin-top:4px;text-transform:uppercase;letter-spacing:.06em}}
.slide.text .body{{align-items:flex-start}}
.diag{{max-width:1040px;width:100%}}
.diag .lead{{font-size:18px;line-height:1.55;margin-bottom:18px}}
.callout{{background:{CARD};border:1px solid {GRID};border-left:4px solid {RUN};border-radius:10px;padding:14px 18px;margin-bottom:12px;font-size:16px;line-height:1.5}}
.callout .k{{display:block;color:{MUTED};font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}}
.obs{{list-style:none}}
.obs li{{padding:9px 0 9px 24px;position:relative;font-size:15px;line-height:1.5;border-bottom:1px solid {GRID}}}
.obs li:before{{content:'▸';position:absolute;left:0;color:{RUN}}}
table.pb{{border-collapse:collapse;font-size:18px;min-width:680px}}
table.pb th{{text-align:left;color:{MUTED};font-size:12px;text-transform:uppercase;letter-spacing:.08em;padding:10px 28px 10px 0;border-bottom:2px solid {GRID}}}
table.pb td{{padding:12px 28px 12px 0;border-bottom:1px solid {GRID}}}
.mono{{font-variant-numeric:tabular-nums;font-weight:700;color:{RUN}}}
.nav{{position:fixed;bottom:20px;left:0;right:0;display:flex;align-items:center;justify-content:center;gap:18px;color:{MUTED};font-size:13px}}
.dots{{display:flex;gap:7px}}
.dot{{width:8px;height:8px;border-radius:50%;background:{GRID};cursor:pointer}}
.dot.on{{background:{RUN}}}
.hint{{position:fixed;bottom:20px;right:28px;color:{GRID};font-size:12px}}
"""

NAV_JS = """
(function(){
  var slides=[].slice.call(document.querySelectorAll('.slide'));
  var dots=[].slice.call(document.querySelectorAll('.dot'));
  var i=0;
  function show(n){
    i=Math.max(0,Math.min(slides.length-1,n));
    slides.forEach(function(s,k){s.classList.toggle('active',k===i)});
    dots.forEach(function(d,k){d.classList.toggle('on',k===i)});
    var c=document.getElementById('counter'); if(c)c.textContent=(i+1)+' / '+slides.length;
  }
  document.addEventListener('keydown',function(e){
    if(e.key==='ArrowRight'||e.key==='ArrowDown'||e.key===' ')show(i+1);
    else if(e.key==='ArrowLeft'||e.key==='ArrowUp')show(i-1);
    else if(e.key==='Home')show(0); else if(e.key==='End')show(slides.length-1);
  });
  document.querySelector('.deck').addEventListener('click',function(e){
    if(e.target.classList.contains('dot'))return; show(i+1);
  });
  dots.forEach(function(d,k){d.addEventListener('click',function(){show(k)})});
  show(0);
})();
"""


def render_html(title: str, slides: List[Tuple[str, str]]) -> str:
    sec = []
    for head, body in slides:
        is_chart = "<svg" in body
        cls = "slide" if (not head or is_chart) else "slide text"
        inner = (f'<h2>{html.escape(head)}</h2>' if head else "") + (
            f'<div class="body">{body}</div>' if head else body)
        sec.append(f'<section class="{cls}">{inner}</section>')
    dots = "".join('<span class="dot"></span>' for _ in slides)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style></head>
<body><div class="deck">{''.join(sec)}</div>
<div class="nav"><span id="counter"></span><div class="dots">{dots}</div></div>
<div class="hint">← → to navigate</div>
<script>{NAV_JS}</script>
</body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render OMPB analysis as a self-contained HTML slide deck.")
    ap.add_argument("--log", help="training-log.jsonl (default: <home>/training-log.jsonl)")
    ap.add_argument("--home", help="OMPB_HOME state dir (default: smart-resolve $OMPB_HOME -> ~/.ompb -> ./.ompb).")
    ap.add_argument("--diagnosis")
    ap.add_argument("--goal")
    ap.add_argument("--pb")
    ap.add_argument("--plan")
    ap.add_argument("--out")
    ap.add_argument("--title", default="Training Analysis")
    ap.add_argument("--tz", help="(reserved) local timezone label")
    args = ap.parse_args(argv)

    home = resolve_home(args.home)
    log = args.log or log_path(home)
    if not os.path.exists(log):
        sys.stderr.write(f"error: log not found: {log}\n")
        return 2
    logdir = os.path.dirname(os.path.abspath(log))

    def discover(opt, name):
        if opt:
            return opt
        cand = os.path.join(logdir, name)
        return cand if os.path.exists(cand) else None

    rows = load_log(log)
    if not rows:
        sys.stderr.write("error: log is empty.\n")
        return 2
    agg = aggregate(rows)
    diagnosis = load_json(discover(args.diagnosis, "diagnosis.json"))
    goal = load_json(discover(args.goal, "goal.json"))
    pb = load_json(discover(args.pb, "pb-history.json"))
    plan = load_json(discover(args.plan, "plan-state.json"))

    slides = build_slides(agg, diagnosis, goal, pb, plan)
    out = args.out or os.path.join(logdir, "decks", f"deck-{dt.date.today().isoformat()}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(args.title, slides))

    optional = [n for n, v in (("diagnosis", diagnosis), ("goal", goal), ("pb", pb), ("plan", plan)) if v]
    sys.stderr.write(
        f"# build_deck.py: {len(slides)} slides from {agg['n_activities']} activities -> {out}\n"
        f"#   optional sources used: {', '.join(optional) if optional else 'none (pure data viz)'}\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
