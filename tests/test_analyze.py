"""Unit tests for the lap-structure analysis engine (scripts/analyze.py).

Run: `python3 tests/test_analyze.py`  (stdlib only).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import analyze  # noqa: E402


def _lap(km, dur, hr=None):
    return {"distance_km": km, "duration_s": dur, "avg_hr": hr}


def test_interval_6x1k():
    laps = [_lap(2.0, 720, hr=128)]  # WU @6:00
    for _ in range(6):
        laps.append(_lap(1.0, 230, hr=168))   # rep @3:50, high HR
        laps.append(_lap(0.4, 168, hr=140))    # jog rest @7:00, HR recovers
    laps.append(_lap(2.0, 720, hr=128))        # CD
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "interval", r["structure"]
    assert r["type"] == "interval" and len(r["reps"]) == 6
    assert "6 × 1 km @ 3:50" in r["rep_summary"]


def test_tempo_block_defers_intensity():
    # a sustained faster block is described as "tempo" structure, but the easy/tempo TYPE
    # is deferred to the calibrated classifier (type=None) — relative pace ≠ absolute intensity
    laps = [_lap(2.0, 720, hr=130), _lap(6.0, 1500, hr=162), _lap(2.0, 720, hr=130)]
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "tempo" and r["type"] is None


def test_relative_fast_block_without_hr_is_not_tempo():
    # an EASY run with a faster section but no HR gap must NOT be called tempo/interval
    laps = [_lap(1.0, 420), _lap(1.0, 360), _lap(1.0, 360), _lap(1.0, 360), _lap(1.0, 420)]
    r = analyze.analyze_laps(laps)  # auto-lap (1km), no HR → no intensity evidence
    assert r["type"] is None and r["structure"] in ("steady", "progression")


def test_progression():
    laps = [_lap(1.0, p) for p in (360, 340, 320, 300, 280, 260)]
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "progression"


def test_steady_defers_type():
    laps = [_lap(1.0, 300 + (i % 2) * 4) for i in range(8)]  # ~5:00 flat
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "steady" and r["type"] is None  # easy/tempo deferred to classifier


def test_steady_long_is_long():
    laps = [_lap(2.0, 720) for _ in range(11)]  # 22 km uniform
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "steady" and r["type"] == "long"


def test_auto_lap_interval_flagged():
    # every lap = 1 km (auto-lap), but alternating fast/slow → still interval, lower confidence
    laps = []
    for i in range(8):
        laps.append(_lap(1.0, 235 if i % 2 == 0 else 410, hr=170 if i % 2 == 0 else 135))
    r = analyze.analyze_laps(laps)
    assert r["structure"] == "interval" and r["confidence"] == "medium"
    assert any("auto-lap" in n for n in r["notes"])


def test_too_few_laps_unknown():
    r = analyze.analyze_laps([_lap(5.0, 1500), _lap(5.0, 1500)])
    assert r["structure"] == "unknown"


def test_splits_negative():
    laps = [_lap(1.0, 320), _lap(1.0, 315), _lap(1.0, 300), _lap(1.0, 295)]  # speeding up
    r = analyze.analyze_laps(laps)
    assert r["splits"]["negative_split"] is True and r["splits"]["fade_pct"] < 0


def test_strava_detail_adapter_to_engine():
    # Strava activity-detail JSON (6×1k intervals) → normalize → engine, end to end, no network
    import import_strava
    laps_raw = [{"distance": 2000, "moving_time": 720, "average_speed": 2.78, "average_heartrate": 130}]
    for _ in range(6):
        laps_raw.append({"distance": 1000, "moving_time": 230, "average_speed": 4.348, "average_heartrate": 168})
        laps_raw.append({"distance": 400, "moving_time": 168, "average_speed": 2.38})
    laps_raw.append({"distance": 2000, "moving_time": 720, "average_speed": 2.78})
    laps, total = import_strava._laps_from_detail({"distance": 12000, "laps": laps_raw})
    assert total == 12.0 and len(laps) == 14
    r = analyze.analyze_laps(laps, distance_km=total)
    assert r["structure"] == "interval" and len(r["reps"]) == 6


# --- stream analysis (decoupling / zones / hard efforts) ------------------------

def _streams(hr, vel, t=None):
    return {"heartrate": hr, "velocity": vel, "time": t or list(range(len(hr)))}


def test_decoupling_drift():
    n = 1500  # 25 min so there's ≥15 min of post-warmup steady data
    vel = [3.0] * (n // 2) + [2.7] * (n - n // 2)   # slows for the same HR
    r = analyze.analyze_streams(_streams([150] * n, vel))
    assert r["decoupling_pct"] > 5 and "high aerobic decoupling" in r["decoupling_note"]


def test_well_coupled():
    r = analyze.analyze_streams(_streams([150] * 1500, [3.0] * 1500))
    assert abs(r["decoupling_pct"]) < 2


def test_decoupling_skipped_when_too_short():
    # a 5-min run is all warm-up → decoupling not reported (no false durability signal)
    r = analyze.analyze_streams(_streams([150] * 300, [3.0] * 300))
    assert "decoupling_pct" not in r


def test_time_in_zone():
    r = analyze.analyze_streams(_streams([150] * 300, [3.0] * 300), hrmax=190)  # 150/190=0.79 → Z3
    assert r["time_in_zone_pct"]["Z3"] >= 90


def test_hard_efforts_count():
    hr = []
    for _ in range(3):
        hr += [120] * 60 + [171] * 70   # easy, then a ≥45s Z5 bout
    hr += [120] * 60
    r = analyze.analyze_streams(_streams(hr, [3.0] * len(hr)), hrmax=190)
    assert r["hard_efforts"] == 3


def test_streams_too_short_noop():
    assert analyze.analyze_streams(_streams([150] * 10, [3.0] * 10)) == {}


def test_strava_streams_adapter():
    import import_strava
    data = {"time": {"data": [0, 1, 2]}, "heartrate": {"data": [150, 151, 152]},
            "velocity_smooth": {"data": [3.0, 3.1, 3.0]}, "distance": {"data": [0, 3, 6]}}
    s = import_strava._streams_from_data(data)
    assert s["heartrate"] == [150, 151, 152] and s["velocity"] == [3.0, 3.1, 3.0]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("analyze: all tests passed")
