"""Unit tests for Strava import: duplicate-upload quality ranking + lap pace accuracy
(scripts/import_strava.py).

Run: `python3 tests/test_import_strava.py`  (stdlib only; no pytest required).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import import_strava as imp  # noqa: E402
import ompb_env  # noqa: E402


def _e(started_at, dist, sid, sport="running", date=None):
    return {"sport": sport, "started_at": started_at, "source_id": sid,
            "date": date or (started_at or "")[:10], "actual": {"distance_km": dist}}


def _seen():
    return {"ids": set(), "prints": set()}


def test_fingerprint_separates_same_day_same_distance_sessions():
    # Warm-up and cool-down on the same day, both 1.5 km, 12 min apart → DIFFERENT sessions.
    # The old (date, distance) fingerprint wrongly merged these, dropping one.
    warmup = _e("2026-06-13T21:56:12Z", 1.5, "strava-A")
    cooldown = _e("2026-06-13T22:08:08Z", 1.5, "strava-B")
    seen = _seen()
    ompb_env.mark_seen(seen, warmup)
    assert ompb_env.dup_kind(seen, cooldown) is None


def test_fingerprint_merges_duplicate_uploads_despite_distance_rounding():
    # Two uploads of one run, 1 s apart, with GPS distances 2.150 vs 2.154 km (which the old
    # fingerprint split into 2.1 vs 2.2). Start time merges them regardless of distance.
    gps = _e("2026-06-13T21:37:29Z", 2.154, "strava-GPS")
    trainer = _e("2026-06-13T21:37:30Z", 2.150, "strava-TRN")
    seen = _seen()
    ompb_env.mark_seen(seen, gps)
    assert ompb_env.dup_kind(seen, trainer) == "cross-source"


def test_fingerprint_merges_across_minute_bucket_edge():
    # A 1 s gap that straddles a minute boundary (:59 → :00) still merges via adjacent buckets.
    a = _e("2026-06-13T22:08:59Z", 5.0, "strava-A")
    b = _e("2026-06-13T22:09:00Z", 5.0, "strava-B")
    seen = _seen()
    ompb_env.mark_seen(seen, a)
    assert ompb_env.dup_kind(seen, b) == "cross-source"


def test_fingerprint_falls_back_to_distance_without_started_at():
    # Pre-existing log entries (no started_at) keep the (date, distance) fingerprint so old
    # logs still dedup across sources.
    old = {"sport": "running", "date": "2026-06-01", "source_id": "strava-X",
           "actual": {"distance_km": 10.0}}
    assert ompb_env.entry_fingerprint(old)[0] == "d"
    seen = _seen()
    ompb_env.mark_seen(seen, old)
    other_source = dict(old, source_id="coros-Y")
    assert ompb_env.dup_kind(seen, other_source) == "cross-source"


def test_activity_quality_prefers_gps_outdoor_over_treadmill():
    # One run uploaded twice (different ids, same date+distance): a GPS/outdoor copy keeps
    # the real per-km pace variation; a treadmill/foot-pod copy is flattened to the average.
    # The GPS copy must rank higher so dedup keeps it.
    gps = {"start_latlng": [37.4, 127.1], "trainer": False, "manual": False}
    treadmill = {"start_latlng": [], "trainer": True, "manual": False}
    assert imp._activity_quality(gps) > imp._activity_quality(treadmill)


def test_activity_quality_prefers_recorded_over_manual():
    recorded = {"start_latlng": [], "trainer": False, "manual": False}
    manual = {"start_latlng": [], "trainer": False, "manual": True}
    assert imp._activity_quality(recorded) > imp._activity_quality(manual)


def test_lap_pace_uses_raw_distance_time_not_rounded_speed():
    # Strava rounds lap average_speed to 2 dp: 1000 m / 396 s = 2.5253 m/s is reported as
    # 2.53. 1000/2.53 = 395.3 s (6:35), but the true pace is 396 s/km (6:36). The lap pace
    # must come from the raw distance + time, not the rounded speed.
    detail = {"distance": 1000,
              "laps": [{"distance": 1000, "moving_time": 396,
                        "elapsed_time": 396, "average_speed": 2.53}]}
    laps, total = imp._laps_from_detail(detail)
    assert laps[0]["pace_sec"] == 396.0
    assert total == 1.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("import_strava: all tests passed")
