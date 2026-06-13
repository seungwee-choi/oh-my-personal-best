"""Unit tests for weather running-advice + parsing (no network — synthetic forecast data).

Run: `python3 tests/test_weather.py`  (stdlib only; no pytest required).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import weather as W  # noqa: E402


# ── pure / offline tests ──────────────────────────────────────────────────────

def test_heat_pace_adjust():
    assert W.heat_pace_adjust(12) == 0           # cool → no penalty
    assert W.heat_pace_adjust(15) == 0
    assert W.heat_pace_adjust(25) == 25          # 10°C over → ~25s/km
    assert W.heat_pace_adjust(40) == 60          # capped
    assert W.heat_pace_adjust(None) == 0


def test_aqi_band():
    assert W.aqi_band(None, None) is None
    assert W.aqi_band(8, 30)["level"] == "good"
    assert W.aqi_band(40, 120)["level"] == "usg"
    assert W.aqi_band(80, 170)["level"] == "unhealthy"


def test_advise_flags_heat_and_air_and_session():
    hot_bad = {"feels": 33, "pm25": 80, "us_aqi": 170, "precip_prob": 10, "wind_max": 12}
    # hard session on a hot day → swap/intensity flag
    a = W.advise(hot_bad, "interval")
    assert a["pace_adjust_s"] > 0 and any("하드세션" in f for f in a["flags"])
    assert a["aqi"]["level"] == "unhealthy"
    # easy on the same day → pace-allowance flag (no swap), still air warning
    e = W.advise(hot_bad, "easy")
    assert any("여유" in f for f in e["flags"])
    # mild clean day → no flags
    assert W.advise({"feels": 13, "pm25": 8, "us_aqi": 25, "precip_prob": 5, "wind_max": 8})["flags"] == []


def test_parse_metno_and_air():
    # minimal Met.no compact timeseries (UTC) + Open-Meteo air quality
    met = {"properties": {"timeseries": [
        {"time": "2026-06-04T03:00:00Z",  # 12:00 KST
         "data": {"instant": {"details": {"air_temperature": 24.0, "relative_humidity": 70, "wind_speed": 3.0}},
                  "next_1_hours": {"summary": {"symbol_code": "clearsky_day"}, "details": {"precipitation_amount": 0}},
                  "next_6_hours": {"summary": {"symbol_code": "fair_day"}, "details": {"precipitation_amount": 0}}}},
        {"time": "2026-06-04T06:00:00Z",
         "data": {"instant": {"details": {"air_temperature": 27.0, "relative_humidity": 65, "wind_speed": 4.0}},
                  "next_6_hours": {"summary": {"symbol_code": "rain"}, "details": {"precipitation_amount": 2.0}}}},
    ]}}
    aq = {"current": {"pm2_5": 11, "pm10": 13, "us_aqi": 86}}
    out = W._parse(met, aq, "Asia/Seoul")
    assert out and out["current"]["temp"] == 24.0 and out["current"]["pm25"] == 11
    assert out["current"]["feels"] is not None      # computed apparent temp
    assert out["current"]["wind"] == round(3.0 * 3.6, 1)  # m/s → km/h
    assert len(out["daily"]) == 1                   # both timesteps are 2026-06-04 KST
    d = out["daily"][0]
    assert d["date"] == "2026-06-04" and d["t_max"] == 27 and d["t_min"] == 24
    assert W._parse({"properties": {"timeseries": []}}, None, "auto") is None


def test_wmo_symbol_labels():
    assert W.wmo("clearsky_day")[0] == "맑음"
    assert W.wmo("rain")[0] == "비"
    assert W.wmo("partlycloudy_night")[0] == "부분 흐림"
    assert W.wmo(None)[0] == "—" and W.wmo("unknown_x")[0] == "—"


def test_geocode_local_kr_table():
    # '성남' must resolve from the local curated table without a network call.
    # We verify by patching _get_json to raise if called.
    original = W._get_json

    def _boom(*a, **k):
        raise AssertionError("local hit must not call the network")

    W._get_json = _boom
    try:
        out = W.geocode_candidates("성남")
        assert out[0]["place"] == "성남시, 경기"
        assert out[0]["tz"] == "Asia/Seoul"
        assert out[0]["country_code"] == "KR"
        assert abs(out[0]["lat"] - 37.42) < 0.01

        # English alias matching
        busan = W.geocode_candidates("Busan")
        assert any("부산" in c["place"] for c in busan)

        # geocode() also uses local table first
        assert W.geocode("성남")["place"] == "성남시, 경기"
    finally:
        W._get_json = original


def test_geocode_fallback_openmeteo():
    # Queries not in the local table fall back to Open-Meteo with KP-last/population ranking.
    fake = {"results": [
        {"name": "Pyongyang", "latitude": 39.0, "longitude": 125.7, "country_code": "KP",
         "country": "조선민주주의인민공화국", "population": 3000000},
        {"name": "Tokyo", "latitude": 35.68, "longitude": 139.69, "country_code": "JP",
         "country": "일본", "population": 9000000, "timezone": "Asia/Tokyo"},
    ]}
    original = W._get_json
    W._get_json = lambda *a, **k: fake
    try:
        out = W.geocode_candidates("xyzcity")
        assert out[0]["place"].startswith("Tokyo")
        assert out[-1]["country_code"] == "KP"      # KP sorted last
    finally:
        W._get_json = original

    W._get_json = lambda *a, **k: {"results": []}
    try:
        assert W.geocode_candidates("zzznope") == []
        assert W.geocode("zzznope") is None
    finally:
        W._get_json = original


def test_apparent_temp_and_dew_point():
    # humid heat feels hotter than dry; missing humidity falls back to temp
    assert W._apparent_temp(30, 90, 1) > W._apparent_temp(30, 30, 1)
    assert W._apparent_temp(20, None, 2) == 20
    assert W._dew_point(25, 60) is not None
    assert W._dew_point(None, 50) is None


def test_rank_results_kp_last():
    res = [
        {"name": "A", "country_code": "KP", "population": 5000000},
        {"name": "B", "country_code": "KR", "population": 1000000},
        {"name": "C", "country_code": "JP", "population": 9000000},
    ]
    ranked = W._rank_results(res)
    assert ranked[-1]["country_code"] == "KP"
    assert ranked[0]["name"] == "C"   # highest population first among non-KP


def test_advise_rain_and_wind_flags():
    rainy = {"feels": 15, "pm25": 5, "us_aqi": 20, "precip_prob": 70, "wind_max": 10}
    a = W.advise(rainy)
    assert any("비" in f for f in a["flags"])

    windy = {"feels": 15, "pm25": 5, "us_aqi": 20, "precip_prob": 10, "wind": 35}
    w = W.advise(windy)
    assert any("강풍" in f for f in w["flags"])


def test_advise_comfort_levels():
    assert W._comfort(32) == "무더위"
    assert W._comfort(26) == "더움"
    assert W._comfort(18) == "쾌적"
    assert W._comfort(5) == "쌀쌀"
    assert W._comfort(-5) == "추위"
    assert W._comfort(None) == ""


def test_candidate_shape():
    r = {"name": "Seoul", "latitude": 37.56, "longitude": 126.97,
         "country_code": "KR", "country": "South Korea", "population": 9000000,
         "timezone": "Asia/Seoul", "admin1": "Seoul"}
    c = W._candidate(r, "Seoul")
    assert c["lat"] == 37.56 and c["lon"] == 126.97
    assert c["tz"] == "Asia/Seoul"
    assert c["country_code"] == "KR"
    assert c["population"] == 9000000


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {name}: {exc}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
