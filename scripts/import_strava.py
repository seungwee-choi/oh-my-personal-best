#!/usr/bin/env python3
"""
import_strava.py — Sync Strava activities into the OMPB training log (standard library only).

Reads the credential file written by strava_connect.py ($OMPB_HOME/strava.json), auto-refreshes
the 6-hour access token using the stored refresh_token + client_id/secret, pages through the
athlete's activities, normalizes each to the training-log schema, and appends new ones (deduped
by source_id) — exactly like import_fit.py. No external dependencies.

For a one-shot sync without a credential file, pass a short-lived token: `--access-token <tok>`
(it cannot self-refresh, so it stops working after ~6 hours; connect via strava_connect.py for
durable auto-refresh).

Usage:
  python3 import_strava.py [--home DIR] [--tz ...] [--max-pages N] [--after YYYY-MM-DD]
  python3 import_strava.py --access-token <6h-token>        # one-shot, no refresh
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ompb_env import (resolve_home, log_path, resolve_lang, star_cta,
                       load_seen, dup_kind, mark_seen, entry_fingerprint)
from classify import name_to_type  # shared title-keyword inference (avoid clash w/ local classify())

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

_RUN = {"run", "trailrun", "virtualrun"}
_CYCLE = {"ride", "virtualride", "ebikeride", "mountainbikeride", "gravelride", "velomobile"}
_SWIM = {"swim"}
_WALK = {"walk"}
_HIKE = {"hike"}


def _get_json(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _post(url, params):
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:  # Strava returns a JSON error body even on 401
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}"}


def get_access_token(cred, cred_path):
    """Return a valid access token, refreshing (and persisting) if expired/near-expiry."""
    now = int(time.time())
    if cred.get("access_token") and cred.get("expires_at", 0) - now > 300:
        return cred["access_token"]
    tok = _post(TOKEN_URL, {
        "client_id": cred["client_id"],
        "client_secret": cred["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": cred["refresh_token"],
    })
    if "access_token" not in tok:
        raise RuntimeError(f"token refresh failed: {tok}. Re-check your Client ID/Secret at "
                           "https://www.strava.com/settings/api, then re-run strava_connect.py.")
    cred["access_token"] = tok["access_token"]
    cred["expires_at"] = tok.get("expires_at")
    if tok.get("refresh_token"):
        cred["refresh_token"] = tok["refresh_token"]  # Strava may rotate it
    with open(cred_path, "w", encoding="utf-8") as fh:
        json.dump(cred, fh, indent=2)
    os.chmod(cred_path, 0o600)
    sys.stderr.write("#   refreshed Strava access token.\n")
    return cred["access_token"]


def pace_from_speed(mps):
    if not mps or mps <= 0:
        return None
    spk = 1000.0 / mps
    return f"{int(spk // 60)}:{int(spk % 60):02d}" if 120 <= spk <= 1200 else None


def running_cadence(avg_cadence):
    if not avg_cadence:
        return None
    v = int(round(avg_cadence))
    if v <= 0:
        return None
    if v < 120:  # Strava running cadence is one-leg rpm -> double to steps/min
        v *= 2
    return v if 100 <= v <= 250 else None


def classify(sport_type, distance_km, long_threshold):
    s = (sport_type or "").lower()
    if s in _RUN:
        if distance_km is not None and distance_km >= long_threshold:
            return "running", "long"
        return "running", "easy"
    if s in _CYCLE:
        return "cycling", "cross"
    if s in _SWIM:
        return "swimming", "cross"
    if s in _WALK:
        return "walking", "cross"
    if s in _HIKE:
        return "hiking", "cross"
    return (s or "unknown"), "cross"


def _activity_quality(a):
    """Richness score for choosing between duplicate uploads of the SAME physical run
    (different Strava ids, identical ``(date, distance)`` fingerprint — e.g. a foot-pod/
    treadmill copy AND a GPS copy of one run). A GPS/outdoor recording carries the real
    per-km pace variation in its streams; a treadmill/foot-pod copy is flattened to the
    average, so its splits read as a near-constant pace. Prefer GPS > non-trainer >
    auto-recorded so the run that preserves the variation wins."""
    q = 0
    if a.get("start_latlng"):   # has a GPS track → real splits/streams survive
        q += 4
    if not a.get("trainer"):    # not flagged treadmill/indoor
        q += 2
    if not a.get("manual"):     # actually recorded, not hand-entered
        q += 1
    return q


def _best_key(best, fp):
    """The existing key in ``best`` this fingerprint belongs to — adjacent minute buckets
    are the same run (mirrors dup_kind) — or ``fp`` itself if none is grouped yet. Keeps the
    in-sync best-pick consistent with the cross-log dedup."""
    if fp and fp[0] == "t":
        for db in (-1, 0, 1):
            k = ("t", fp[1], fp[2] + db)
            if k in best:
                return k
    return fp


def to_entry(a, long_threshold):
    dist_m = a.get("distance")
    distance_km = round(dist_m / 1000.0, 3) if dist_m else None
    sport, ompb_type = classify(a.get("sport_type") or a.get("type"), distance_km, long_threshold)
    is_run = sport == "running"
    date = (a.get("start_date_local") or a.get("start_date") or "")[:10]
    if not date:
        return None
    dur = a.get("moving_time") or a.get("elapsed_time")
    hr = a.get("has_heartrate")

    # Refine the run type from Strava's own high-confidence signals, before metric
    # reclassification: the activity title (highest confidence) > Strava's workout_type
    # tag (runs: 1=race, 2=long run, 3=workout). type_source marks these so reclassify.py
    # keeps them. Easy/long-by-distance stays the default for untitled, untagged runs.
    type_source = None
    if is_run:
        named = name_to_type(a.get("name"))
        wt = a.get("workout_type")
        if named:
            ompb_type, type_source = named, "name"
        elif wt == 1:
            ompb_type, type_source = "race", "strava"
        elif wt == 2:
            ompb_type, type_source = "long", "strava"
        elif wt == 3 and not hr:
            ompb_type, type_source = "tempo", "strava"  # tagged a workout, no HR to refine

    actual = {
        "distance_km": distance_km,
        "pace": pace_from_speed(a.get("average_speed")) if is_run else None,
        "avg_hr": int(a["average_heartrate"]) if hr and a.get("average_heartrate") else None,
        "max_hr": int(a["max_heartrate"]) if hr and a.get("max_heartrate") else None,
        "cadence": running_cadence(a.get("average_cadence")) if is_run else None,
        "rpe": None,
        "duration_s": int(dur) if dur else None,
        "calories": int(a["calories"]) if a.get("calories") else None,
        "ascent_m": int(a["total_elevation_gain"]) if a.get("total_elevation_gain") is not None else None,
    }
    entry = {
        "date": date,
        "type": ompb_type,
        "planned": None,
        "actual": actual,
        "sport": sport,
        "source": "strava",
        "source_id": f"strava-{a.get('id')}",
        # UTC start instant — drives the start-time dedup fingerprint (entry_fingerprint),
        # so two uploads of one run (watch + phone, GPS + treadmill) collapse while distinct
        # same-day, same-distance sessions stay separate.
        "started_at": a.get("start_date") or a.get("start_date_local"),
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if type_source:
        entry["type_source"] = type_source
    return entry


def _laps_from_detail(detail: dict):
    """Normalize a Strava activity-detail dict's `laps` → (laps, total_km) for analyze.py."""
    laps = []
    for lp in detail.get("laps") or []:
        d = lp.get("distance")
        dur = lp.get("moving_time") or lp.get("elapsed_time")
        # Pace from distance/time directly. Strava rounds lap ``average_speed`` to 2 dp,
        # so ``1000/average_speed`` drifts up to ~1 s/km vs the true pace — n:nn the runner
        # sees in Garmin/Strava. The raw distance + time give the exact figure.
        laps.append({
            "distance_km": round(d / 1000.0, 3) if d else None,
            "duration_s": int(dur) if dur else None,
            "pace_sec": (dur / (d / 1000.0)) if (d and dur) else None,
            "avg_hr": int(lp["average_heartrate"]) if lp.get("average_heartrate") else None,
            "max_hr": int(lp["max_heartrate"]) if lp.get("max_heartrate") else None,
        })
    total = detail.get("distance")
    return laps, (round(total / 1000.0, 3) if total else None)


def fetch_detail(activity_id, home=None) -> dict:
    """Fetch one activity's detail object from Strava (1 API call). On-demand only."""
    aid = str(activity_id).replace("strava-", "")
    home = resolve_home(home)
    cred_path = os.path.join(home, "strava.json")
    if not os.path.exists(cred_path):
        raise RuntimeError(f"{cred_path} not found — run strava_connect.py first.")
    with open(cred_path, encoding="utf-8") as fh:
        cred = json.load(fh)
    token = get_access_token(cred, cred_path)
    return _get_json(f"https://www.strava.com/api/v3/activities/{aid}?include_all_efforts=false", token)


def _meta_from_detail(detail: dict) -> dict:
    """Card header fields from a Strava detail object: date + the device sport label."""
    return {"date": (detail.get("start_date_local") or detail.get("start_date") or "")[:10] or None,
            "sport_type": detail.get("sport_type") or detail.get("type")}


def laps_from_strava(activity_id, home=None):
    """Fetch one activity's laps from Strava (1 API call). Returns (laps, total_km)."""
    return _laps_from_detail(fetch_detail(activity_id, home))


def _streams_from_data(data: dict) -> dict:
    """Normalize Strava's key_by_type streams → {time, heartrate, velocity, distance, grade, altitude}."""
    def col(k):
        return (data.get(k) or {}).get("data")
    s = {"time": col("time"), "heartrate": col("heartrate"),
         "velocity": col("velocity_smooth"), "distance": col("distance")}
    if col("grade_smooth"):
        s["grade"] = col("grade_smooth")     # percent
    if col("altitude"):
        s["altitude"] = col("altitude")      # metres
    return s


def laps_from_strava_streams(activity_id, home=None):
    """Fetch per-second streams for one activity (1 API call). Returns the normalized dict
    (see _streams_from_data). On-demand single-activity only — never bulk."""
    aid = str(activity_id).replace("strava-", "")
    home = resolve_home(home)
    cred_path = os.path.join(home, "strava.json")
    if not os.path.exists(cred_path):
        raise RuntimeError(f"{cred_path} not found — run strava_connect.py first.")
    with open(cred_path, encoding="utf-8") as fh:
        cred = json.load(fh)
    token = get_access_token(cred, cred_path)
    url = (f"https://www.strava.com/api/v3/activities/{aid}/streams"
           "?keys=time,heartrate,velocity_smooth,distance,grade_smooth,altitude&key_by_type=true")
    return _streams_from_data(_get_json(url, token))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sync Strava activities into the OMPB training log.")
    ap.add_argument("--home", help="OMPB_HOME (default: smart-resolve).")
    ap.add_argument("--tz", help="(reserved) Strava already provides local dates.")
    ap.add_argument("--access-token", help="One-shot token (no refresh); skips strava.json.")
    ap.add_argument("--long-threshold", type=float, default=19.0)
    ap.add_argument("--per-page", type=int, default=200)
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--after", help="Only activities on/after this date (YYYY-MM-DD).")
    ap.add_argument("--stdout", action="store_true", help="Write JSONL to stdout instead of the home log.")
    args = ap.parse_args(argv)

    home = resolve_home(args.home, create=True)
    target = log_path(home)

    if args.access_token:
        token = args.access_token
    else:
        cred_path = os.path.join(home, "strava.json")
        if not os.path.exists(cred_path):
            sys.stderr.write(f"error: {cred_path} not found. Run strava_connect.py first "
                             "(or pass --access-token for a one-shot sync).\n")
            return 2
        with open(cred_path, encoding="utf-8") as fh:
            cred = json.load(fh)
        try:
            token = get_access_token(cred, cred_path)
        except Exception as e:
            sys.stderr.write(f"error: {e}\n")
            return 1

    after_epoch = None
    if args.after:
        after_epoch = int(datetime.strptime(args.after, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    # Serialize concurrent syncs of the SAME log. Two overlapping syncs (e.g. the connect
    # callback + the manual sync FAB) each read the log before the other writes, so both
    # append the same activity → duplicates. An exclusive lock on the log file makes the
    # second sync wait, then load_seen() sees the first's writes and skips them. Released on
    # close() in the finally block. (stdout mode writes no file, so it needs no lock.)
    sink = sys.stdout if args.stdout else open(target, "a", encoding="utf-8")
    if sink is not sys.stdout:
        import fcntl
        fcntl.flock(sink.fileno(), fcntl.LOCK_EX)
    seen = load_seen(target)  # AFTER the lock, so a concurrent sync's appends are visible
    emitted = skipped = xsrc = errored = page = 0
    by_sport = {}
    fetched = []  # raw activities across all pages, so we can resolve same-sync duplicates
    try:
        for page in range(1, args.max_pages + 1):
            params = {"per_page": args.per_page, "page": page}
            if after_epoch:
                params["after"] = after_epoch
            try:
                acts = _get_json(ACTIVITIES_URL + "?" + urllib.parse.urlencode(params), token)
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"error: Strava API {e.code} on page {page}"
                                 + (" (rate limited — wait 15 min)\n" if e.code == 429 else "\n"))
                break
            if not acts:
                break
            fetched.extend(acts)

        # When one run is uploaded from two sources (different ids, same (date, distance)
        # fingerprint), Strava returns newest-first, so a naive first-wins dedup can keep
        # the poorer copy (a treadmill/foot-pod upload flattens per-km pace to the average).
        # Pick the richest upload per fingerprint up front so the GPS/outdoor version wins;
        # lower-quality duplicates from THIS sync are then skipped as cross-source.
        best = {}  # fingerprint -> (quality, source_id)
        for a in fetched:
            e = to_entry(a, args.long_threshold)
            if e is None:
                continue
            fp = entry_fingerprint(e)
            if fp is None:
                continue
            k = _best_key(best, fp)
            q = _activity_quality(a)
            if k not in best or q > best[k][0]:
                best[k] = (q, e["source_id"])

        for a in fetched:
            entry = to_entry(a, args.long_threshold)
            if entry is None:
                continue
            fp = entry_fingerprint(entry)
            if fp is not None and best[_best_key(best, fp)][1] != entry["source_id"]:
                skipped += 1  # a lower-quality duplicate of this run within the same sync
                xsrc += 1
                continue
            dk = dup_kind(seen, entry)
            if dk:
                skipped += 1
                if dk == "cross-source":
                    xsrc += 1
                continue
            line = json.dumps(entry, ensure_ascii=False)
            json.loads(line)  # integrity guard
            mark_seen(seen, entry)
            sink.write(line + "\n")
            emitted += 1
            by_sport[entry["sport"]] = by_sport.get(entry["sport"], 0) + 1
    finally:
        if sink is not sys.stdout:
            sink.close()

    sys.stderr.write(f"# import_strava.py: {emitted} new activities, {skipped} duplicates skipped"
                     + (f" ({xsrc} cross-source — same activity already imported from another source)" if xsrc else "")
                     + ("" if args.stdout else f"; appended to {target}") + ".\n")
    if by_sport:
        sys.stderr.write("#   by sport: " + ", ".join(f"{k}={v}" for k, v in sorted(by_sport.items())) + "\n")
    if emitted and not args.stdout:
        star_cta(home, resolve_lang(None, home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
