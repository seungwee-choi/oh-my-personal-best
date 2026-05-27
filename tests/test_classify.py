"""Unit tests for the calibrated training-type classifier (scripts/classify.py).

Run: `python3 tests/test_classify.py`  (stdlib only; no pytest required).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import classify  # noqa: E402

# Fixed bands so the type logic is tested independently of calibration variance.
REF = {"recovery_hr": 130, "tempo_hr": 155, "hard_hr": 165,
       "spread_interval": 24, "spread_steady": 13, "fast_pace": 270, "easy_slow": 390}


def _a(**kw):
    return kw


def test_long_is_distance_first():
    assert classify.refine(_a(avg_hr=140), 22.0, REF) == "long"
    assert classify.refine(_a(avg_hr=170, max_hr=185, pace="4:00"), 25.0, REF) == "long"


def test_interval_needs_peak_and_spread():
    # high peak + big avg→max swing → interval
    assert classify.refine(_a(avg_hr=150, max_hr=182, pace="4:30"), 10.0, REF) == "interval"
    # high peak but steady (small spread) → tempo, not interval
    assert classify.refine(_a(avg_hr=160, max_hr=166, pace="4:10"), 8.0, REF) == "tempo"


def test_tempo_sustained_high_hr():
    assert classify.refine(_a(avg_hr=158, max_hr=164, pace="4:20"), 9.0, REF) == "tempo"


def test_recovery_low_slow_short():
    assert classify.refine(_a(avg_hr=120, max_hr=135, pace="7:00", duration_s=1800), 5.0, REF) == "recovery"
    # low HR but long/normal distance → NOT recovery (just easy)
    assert classify.refine(_a(avg_hr=120, max_hr=135, pace="7:00"), 14.0, REF) == "easy"


def test_easy_is_the_default():
    assert classify.refine(_a(avg_hr=140, max_hr=150, pace="6:00"), 10.0, REF) == "easy"


def test_pace_only_fallback_without_hr():
    assert classify.refine(_a(pace="4:20"), 10.0, REF) == "tempo"     # fast
    assert classify.refine(_a(pace="7:10"), 6.0, REF) == "recovery"   # very slow + short
    assert classify.refine(_a(pace="6:00"), 10.0, REF) == "easy"


def test_calibrate_produces_sane_bands():
    runs = [{"sport": "running", "actual": {"avg_hr": 130 + (i % 30), "max_hr": 150 + (i % 30),
                                            "pace": "6:00"}} for i in range(60)]
    # several genuine hard efforts (P99 ignores a *lone* spike — needs a few near max)
    for _ in range(5):
        runs.append({"sport": "running", "actual": {"avg_hr": 165, "max_hr": 185, "pace": "4:00"}})
    runs.append({"sport": "cycling", "actual": {"avg_hr": 140, "max_hr": 160}})  # ignored (not running)
    ref = classify.calibrate(runs)
    assert ref["has_hr"] and ref["hrmax"] >= 180
    assert ref["recovery_hr"] < ref["tempo_hr"] < ref["hard_hr"]
    assert ref["spread_steady"] < ref["spread_interval"]


def test_no_signal_is_easy():
    assert classify.refine({}, None, REF) == "easy"
    assert classify.refine(_a(distance_km=5), 5.0, {}) == "easy"  # empty ref, no HR/pace


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("classify: all tests passed")
