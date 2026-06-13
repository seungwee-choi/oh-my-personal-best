"""HR-zone table and manual HRmax override for the oh-my-personal-best deterministic toolkit.

Stdlib only. Imports siblings via `from ompb_env import ...`. Never imports ompb_core.

HR zones are %HRmax bands (Z1<60 · Z2 60-70 · Z3 70-80 · Z4 80-90 · Z5 >=90). HRmax is
normally calibrated from the log (99th-pct of recorded session max HR). A manual `hrmax`
override stored in config.json is preferred over the log estimate and flows into time-in-zone,
the diagnostic review, and zone insights throughout the toolkit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from ompb_env import resolve_home

# %HRmax band edges (mirror core analyze._zone_idx): Z1<60 Z2 60-70 Z3 70-80 Z4 80-90 Z5 >=90.
_ZONE_EDGES = [0.0, 0.60, 0.70, 0.80, 0.90, 1.0]
_ZONE_LABELS = ["Z1", "Z2", "Z3", "Z4", "Z5"]
_ZONE_NAMES = ["회복", "유산소(이지)", "템포(역치 아래)", "역치", "VO2max"]


# ---------------------------------------------------------------------------
# Inline stdlib helpers (no pb module in the plugin)
# ---------------------------------------------------------------------------

def _home(home: Optional[str]) -> str:
    return home or resolve_home(create=True)


def _load_log(home: str) -> list:
    path = os.path.join(home, "training-log.jsonl")
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def _pace_sec(pace) -> Optional[int]:
    if not pace or ":" not in str(pace):
        return None
    try:
        mm, ss = str(pace).split(":")[:2]
        return int(mm) * 60 + int(ss)
    except ValueError:
        return None


def _is_run(r: dict) -> bool:
    """A running activity. Strava imports tag sport="running"; CSV imports omit sport
    entirely — treat a missing sport as a run unless it's typed cross."""
    if r.get("sport") not in (None, "running"):
        return False
    return r.get("type") != "cross"


# ---------------------------------------------------------------------------
# Config helpers (local, stdlib only)
# ---------------------------------------------------------------------------

def _config_path(home: str) -> str:
    return os.path.join(home, "config.json")


def _read_config(home: str) -> dict:
    p = _config_path(home)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return {}


def _write_config(home: str, cfg: dict) -> None:
    with open(_config_path(home), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _pct(vals: List[float], q: float) -> Optional[float]:
    """q-quantile (0..1) of vals, nearest-rank. None on empty."""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def _hr_pace(home: str):
    """(max_hrs, avg_hrs, paces_sec) over running entries — mirrors core classify.calibrate inputs."""
    max_hrs, avg_hrs, paces = [], [], []
    for r in _load_log(home):
        if not _is_run(r):
            continue
        a = r.get("actual") or {}
        if a.get("max_hr"):
            max_hrs.append(a["max_hr"])
        if a.get("avg_hr"):
            avg_hrs.append(a["avg_hr"])
        ps = _pace_sec(a.get("pace"))
        if ps:
            paces.append(ps)
    return max_hrs, avg_hrs, paces


def _hrmax_estimated(max_hrs: List[float], avg_hrs: List[float]) -> Optional[float]:
    """Log-calibrated HRmax: 99th-pct of session max HR, else 1.10x the highest average HR.
    None when there is no HR data at all."""
    p99 = _pct(max_hrs, 0.99)
    if p99:
        return p99
    return max(avg_hrs) * 1.10 if avg_hrs else None


def _zone_table(hrmax: float) -> List[dict]:
    """[{zone, name, lo_pct, hi_pct, lo_bpm, hi_bpm}] for Z1-Z5 (top zone hi is open-ended)."""
    out = []
    for i, label in enumerate(_ZONE_LABELS):
        lo_p, hi_p = _ZONE_EDGES[i], _ZONE_EDGES[i + 1]
        out.append({
            "zone": label, "name": _ZONE_NAMES[i],
            "lo_pct": int(round(lo_p * 100)), "hi_pct": int(round(hi_p * 100)),
            "lo_bpm": int(round(lo_p * hrmax)) if i > 0 else None,
            "hi_bpm": int(round(hi_p * hrmax)) if i < len(_ZONE_LABELS) - 1 else None,
        })
    return out


def _fmt_pace(sec: Optional[float]) -> Optional[str]:
    if not sec:
        return None
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def current(home: Optional[str] = None) -> dict:
    """The runner's current zone basis for display: HRmax + whether it's a manual override or a
    log estimate, the resulting zone table, the HR-data coverage, and pace bands."""
    home = _home(home)
    cfg = _read_config(home)
    max_hrs, avg_hrs, paces = _hr_pace(home)
    estimated = _hrmax_estimated(max_hrs, avg_hrs)

    manual = cfg.get("hrmax")
    try:
        manual = float(manual) if manual else None
    except (TypeError, ValueError):
        manual = None

    hrmax = manual or estimated
    source = "manual" if manual else ("estimated" if estimated else "none")
    return {
        "hrmax": int(round(hrmax)) if hrmax else None,
        "source": source,                        # manual | estimated | none
        "estimated_hrmax": int(round(estimated)) if estimated else None,
        "hr_runs": len(max_hrs),                 # runs carrying a recorded max HR
        "zones": _zone_table(hrmax) if hrmax else [],
        "pace_bands": {
            "fast": _fmt_pace(_pct(paces, 0.20)),       # quickest fifth of runs
            "easy_slow": _fmt_pace(_pct(paces, 0.72)),  # slowest ~quarter (recovery-slow)
        },
    }


def set_hrmax(home: Optional[str], value) -> dict:
    """Persist a manual HRmax override into config.json (merging, preserving language etc.).
    Returns the refreshed ``current`` view. Raises ValueError on an implausible value."""
    home = _home(home)
    v = int(round(float(value)))
    if not (120 <= v <= 230):
        raise ValueError("HRmax는 120~230 사이의 값이어야 해요")
    cfg = _read_config(home)
    cfg["hrmax"] = v
    _write_config(home, cfg)
    return current(home)


def clear_hrmax(home: Optional[str] = None) -> dict:
    """Remove the manual override -> revert to log calibration. Returns the refreshed view."""
    home = _home(home)
    cfg = _read_config(home)
    cfg.pop("hrmax", None)
    _write_config(home, cfg)
    return current(home)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Show or edit the runner's HR-zone basis (HRmax + zone table)."
    )
    ap.add_argument("--home", help="Explicit OMPB_HOME override.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("show", help="Print current zone table as JSON.")

    set_p = sub.add_parser("set", help="Set a manual HRmax override in config.json.")
    set_p.add_argument("--hrmax", type=int, required=True, help="HRmax value (120-230).")

    sub.add_parser("clear", help="Remove the manual HRmax override.")

    args = ap.parse_args(argv)

    if args.cmd == "show" or args.cmd is None:
        print(json.dumps(current(args.home), ensure_ascii=False, indent=2))
    elif args.cmd == "set":
        result = set_hrmax(args.home, args.hrmax)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "clear":
        result = clear_hrmax(args.home)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
