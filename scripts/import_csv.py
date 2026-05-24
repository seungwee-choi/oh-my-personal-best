"""
import_csv.py — Normalize Strava / Garmin / Coros activity CSV exports to
oh-my-personal-best training-log JSONL format.

Reads an activity CSV file and writes one JSON object per activity to stdout.
Each object conforms to the training-log.jsonl schema used by OMPB:

  {
    "date":      "YYYY-MM-DD",
    "type":      "easy|long|tempo|interval|recovery|race|cross|rest",
    "planned":   null,
    "actual": {
      "distance_km": float | null,
      "pace":        "MM:SS" | null,
      "avg_hr":      int | null,
      "max_hr":      int | null,
      "cadence":     int | null,
      "rpe":         null
    },
    "source":    "csv",
    "logged_at": "ISO-8601"
  }

Usage:
    python3 import_csv.py <file.csv>
    python3 import_csv.py garmin_activities.csv > training-log-import.jsonl

Column-name variants handled case-insensitively (partial list):
  Date         : Date, Activity Date, start_time, Start Time, timestamp
  Distance     : Distance, distance_km, Distance (km), distance_miles, Distance (mi)
  Moving Time  : Moving Time, moving_time, Elapsed Time, elapsed_time, Duration, duration
  Avg Pace     : Average Pace, avg_pace, Avg Pace, Pace
  Avg HR       : Average Heart Rate, avg_hr, Avg HR, avg_heart_rate
  Max HR       : Max Heart Rate, max_hr, Max HR, max_heart_rate
  Cadence      : Average Cadence, avg_cadence, Cadence, cadence
  Activity Name: Activity Name, name, Title, title
  Activity Type: Activity Type, type, sport_type, Sport
"""

import argparse
import csv
import json
import re
import sys

from ompb_env import resolve_home, log_path
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Column-name resolution helpers
# ---------------------------------------------------------------------------

def _find_col(header: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first header entry that matches any candidate (case-insensitive)."""
    lower_header = {col.strip().lower(): col for col in header}
    for cand in candidates:
        match = lower_header.get(cand.lower())
        if match is not None:
            return match
    return None


def _get(row: Dict, col: Optional[str], default=None):
    """Safely retrieve a value from a csv row dict; return default if col is None or missing."""
    if col is None:
        return default
    val = row.get(col, default)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    return val.strip() if isinstance(val, str) else val


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def parse_date(raw: Optional[str]) -> Optional[str]:
    """Parse a date/datetime string to YYYY-MM-DD. Returns None on failure."""
    if not raw:
        return None
    raw = raw.strip()
    # Try common formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%b %d, %Y, %H:%M:%S %p",  # Strava: "Mar 15, 2024, 7:00:00 AM"
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Last resort: take first 10 chars if they look like YYYY-MM-DD
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return None


def parse_distance_km(raw: Optional[str], col_name: Optional[str]) -> Optional[float]:
    """Parse distance, converting miles to km when the column name implies miles."""
    if not raw:
        return None
    s = str(raw).strip()
    # Handle locale decimal comma ("10,5" -> 10.5) vs thousands comma ("1,234.5").
    if re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        val = float(s)
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    # Convert miles to km if column name contains 'mi' or 'mile'
    if col_name and any(t in col_name.lower() for t in ("mi", "mile")):
        val = round(val * 1.60934, 3)
    # Sanity: a single session over 100 km is almost certainly malformed input.
    if val > 100:
        return None
    return round(val, 3)


def parse_seconds(raw: Optional[str]) -> Optional[int]:
    """Parse a duration/time string to total seconds. Accepts HH:MM:SS, MM:SS, or plain seconds."""
    if not raw:
        return None
    raw = str(raw).strip()
    parts = raw.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def compute_pace_from_dist_time(distance_km: Optional[float], moving_seconds: Optional[int]) -> Optional[str]:
    """Derive pace as MM:SS/km from distance and moving time in seconds."""
    if not distance_km or not moving_seconds or distance_km <= 0 or moving_seconds <= 0:
        return None
    secs_per_km = moving_seconds / distance_km
    # Sanity: drop physiologically impossible paces (same bound as parse_pace).
    if not (120 <= secs_per_km <= 1200):
        return None
    minutes = int(secs_per_km // 60)
    seconds = int(secs_per_km % 60)
    return f"{minutes}:{seconds:02d}"


def parse_pace(raw: Optional[str]) -> Optional[str]:
    """
    Parse a pace string to MM:SS/km.
    Handles 'MM:SS', 'MM:SS /km', 'MM:SS/km', 'H:MM:SS' (treated as bad data → None).
    Strava sometimes exports pace as 'M:SS /mi' — convert to /km.
    """
    if not raw:
        return None
    raw = str(raw).strip()
    is_per_mile = "/mi" in raw.lower() or "per mi" in raw.lower()
    # Strip units
    clean = raw.lower().replace("/km", "").replace("/mi", "").replace("per mile", "").replace("per km", "").strip()
    secs = parse_seconds(clean)
    if secs is None or secs <= 0:
        return None
    if is_per_mile:
        secs = int(secs / 1.60934)
    minutes = secs // 60
    seconds = secs % 60
    # Sanity: pace between 2:00 and 20:00 /km
    if not (120 <= secs <= 1200):
        return None
    return f"{minutes}:{seconds:02d}"


def parse_hr(raw: Optional[str]) -> Optional[int]:
    """Parse a heart-rate value to int bpm."""
    if not raw:
        return None
    try:
        val = int(float(str(raw).strip()))
        return val if 30 <= val <= 250 else None
    except (ValueError, TypeError):
        return None


def parse_cadence(raw: Optional[str]) -> Optional[int]:
    """Parse cadence (steps/min). Garmin often exports half-cadence (one foot); double if < 100."""
    if not raw:
        return None
    try:
        val = int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    # Double half-cadence values (Garmin exports single-foot spm)
    if val < 100:
        val *= 2
    return val if 100 <= val <= 250 else None


# ---------------------------------------------------------------------------
# Activity type inference
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: List[tuple] = [
    # Race requires an explicit race word — bare distances ("10k", "marathon") are
    # routinely used to name training runs and would trigger false PB detection.
    ("race",     ["race", "competition", "parkrun"]),
    ("interval", ["interval", "track", "speed", "vo2", "repeat", "fartlek"]),
    ("tempo",    ["tempo", "threshold", "lactate", "cruise"]),
    ("long",     ["long run", "long", "lsd", "endurance"]),
    ("recovery", ["recovery", "jog", "shake out", "shakeout", "regeneration", "regen"]),
    ("cross",    ["cycling", "bike", "swim", "elliptical", "pool", "yoga", "hike", "walk",
                  "strength", "gym", "weights", "cross"]),
    ("rest",     ["rest", "off"]),
    ("easy",     ["easy", "base", "aerobic", "run"]),  # catch-all for runs
]


def infer_type(name_raw: Optional[str], type_raw: Optional[str]) -> str:
    """Infer session type from activity name and/or type column. Defaults to 'easy'."""
    combined = " ".join(filter(None, [name_raw, type_raw])).lower()
    if not combined.strip():
        return "easy"
    for session_type, keywords in _TYPE_KEYWORDS:
        for kw in keywords:
            if kw in combined:
                return session_type
    return "easy"


# ---------------------------------------------------------------------------
# Main row processor
# ---------------------------------------------------------------------------

def process_row(row: Dict, header: List[str], logged_at: str) -> Optional[Dict]:
    """Convert one CSV row to a training-log.jsonl dict. Returns None if row should be skipped."""

    # --- Column resolution (resolved once per file, passed via closure in practice,
    #     but resolved per-row here for clarity — negligible cost on typical CSV sizes) ---
    col_date      = _find_col(header, ["date", "activity date", "start_time", "start time", "timestamp"])
    col_dist      = _find_col(header, ["distance", "distance_km", "distance (km)",
                                        "distance_miles", "distance (mi)", "distance (miles)"])
    col_time      = _find_col(header, ["moving time", "moving_time", "elapsed time",
                                        "elapsed_time", "duration", "time"])
    col_pace      = _find_col(header, ["average pace", "avg_pace", "avg pace", "pace"])
    col_avg_hr    = _find_col(header, ["average heart rate", "avg_hr", "avg hr",
                                        "avg heart rate", "average hr", "heart rate"])
    col_max_hr    = _find_col(header, ["max heart rate", "max_hr", "max hr",
                                        "maximum heart rate"])
    col_cadence   = _find_col(header, ["average cadence", "avg_cadence", "cadence",
                                        "avg cadence"])
    col_name      = _find_col(header, ["activity name", "name", "title"])
    col_type      = _find_col(header, ["activity type", "type", "sport_type", "sport"])

    # --- Date ---
    date_str = parse_date(_get(row, col_date))
    if not date_str:
        return None  # Cannot place this entry in the log without a date

    # --- Distance ---
    distance_km = parse_distance_km(_get(row, col_dist), col_dist)

    # --- Moving time → pace fallback ---
    moving_secs = parse_seconds(_get(row, col_time))

    # --- Pace ---
    pace_raw = _get(row, col_pace)
    pace = parse_pace(pace_raw)
    if pace is None and distance_km and moving_secs:
        pace = compute_pace_from_dist_time(distance_km, moving_secs)

    # --- HR ---
    avg_hr = parse_hr(_get(row, col_avg_hr))
    max_hr = parse_hr(_get(row, col_max_hr))

    # --- Cadence ---
    cadence = parse_cadence(_get(row, col_cadence))

    # --- Type inference ---
    name_raw = _get(row, col_name)
    type_raw = _get(row, col_type)
    session_type = infer_type(name_raw, type_raw)

    # Skip non-run activities that are clearly not relevant (optional: keep cross-training)
    # We keep everything so data-logger can decide what to ingest.

    return {
        "date": date_str,
        "type": session_type,
        "planned": None,
        "actual": {
            "distance_km": distance_km,
            "pace": pace,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "cadence": cadence,
            "rpe": None,
        },
        "source": "csv",
        "logged_at": logged_at,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a Strava / Garmin / Coros activity CSV export to "
            "oh-my-personal-best training-log JSONL format.\n\n"
            "Outputs one JSON object per activity to stdout. "
            "Pipe the output into data-logger or append to training-log.jsonl.\n\n"
            "Example:\n"
            "  python3 import_csv.py garmin_activities.csv\n"
            "  python3 import_csv.py strava_export.csv >> .ompb/training-log.jsonl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Path to the CSV file to import")
    parser.add_argument("--home", help="OMPB_HOME state dir (default: smart-resolve $OMPB_HOME -> ~/.ompb -> ./.ompb).")
    parser.add_argument("--stdout", action="store_true", help="Write JSONL to stdout instead of appending to the home log.")
    args = parser.parse_args()

    logged_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    home = resolve_home(args.home, create=True)
    target = log_path(home)
    sink = sys.stdout if args.stdout else open(target, "a", encoding="utf-8")

    emitted = 0
    skipped = 0
    try:
        with open(args.file, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                print(json.dumps({"error": "CSV file has no header row"}), file=sys.stderr)
                sys.exit(1)
            header = list(reader.fieldnames)
            for row in reader:
                entry = process_row(row, header, logged_at)
                if entry is not None:
                    line = json.dumps(entry, ensure_ascii=False)
                    json.loads(line)  # integrity guard: never write a line that won't parse back
                    sink.write(line + "\n")
                    emitted += 1
                else:
                    skipped += 1
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.file}"}), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
    finally:
        if sink is not sys.stdout:
            sink.close()

    print(
        f"# import_csv.py: {emitted} activities emitted, {skipped} rows skipped (no date)."
        + ("" if args.stdout else f" appended to: {target}"),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
