"""Unit tests for Strava import: duplicate-upload quality ranking + lap pace accuracy
(scripts/import_strava.py).

Run: `python3 tests/test_import_strava.py`  (stdlib only; no pytest required).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import import_strava as imp  # noqa: E402


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
