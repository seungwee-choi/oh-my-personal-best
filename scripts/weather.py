"""Weather for training — forecast + air quality + running-specific advice.

Part of the oh-my-personal-best deterministic toolkit (stdlib only — no third-party deps).
Forecast is fetched from Met.no + Open-Meteo and cached in $OMPB_HOME/weather.json (2h TTL).
Location is resolved once and cached in $OMPB_HOME/config.json (wx_lat/wx_lon/wx_place/wx_tz).

Sources (all free, no API key):
- **Forecast**: Met.no locationforecast/2.0/compact — government-grade, stable.
  Apparent temperature and dew point are computed from temp+humidity+wind (Met.no omits them).
- **Air quality**: Open-Meteo air-quality endpoint (PM2.5/PM10/US-AQI — key for Korea).
- **Geocoding**: Open-Meteo geocoding (city → lat/lon + timezone), with a local curated
  table of Korean major cities to handle bare short-name queries ('성남' → '성남시, 경기')
  that Open-Meteo can't match.

Everything is best-effort: a network/parse failure degrades to None / stale cache and never
breaks a page. The running advice (heat/dew-point pace adjustment, AQI flag) is deterministic.

Note on Strava athlete-city: the plugin path has no Strava athlete-city helper yet
(that lives in ompb-apps). The get_location() function wraps the lookup in try/except and
treats a missing city as None, falling back to manual location only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Optional

from ompb_env import resolve_home

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_MET = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
_MET_UA = "OMPB-running-coach/1.0 (coach.overflow.run)"   # Met.no requires an identifying UA
_TTL_S = 2 * 3600

# Met.no symbol_code (base, after stripping _day/_night/_polartwilight) → (한국어, emoji)
_SYM = {
    "clearsky": ("맑음", "☀️"), "fair": ("대체로 맑음", "🌤"), "partlycloudy": ("부분 흐림", "⛅"),
    "cloudy": ("흐림", "☁️"), "fog": ("안개", "🌫"),
    "lightrain": ("약한 비", "🌦"), "rain": ("비", "🌧"), "heavyrain": ("강한 비", "🌧"),
    "lightrainshowers": ("약한 소나기", "🌦"), "rainshowers": ("소나기", "🌦"), "heavyrainshowers": ("강한 소나기", "🌧"),
    "lightsleet": ("약한 진눈깨비", "🌨"), "sleet": ("진눈깨비", "🌨"), "heavysleet": ("강한 진눈깨비", "🌨"),
    "lightsleetshowers": ("약한 진눈깨비", "🌨"), "sleetshowers": ("진눈깨비", "🌨"),
    "lightsnow": ("약한 눈", "🌨"), "snow": ("눈", "🌨"), "heavysnow": ("강한 눈", "❄️"),
    "lightsnowshowers": ("약한 눈", "🌨"), "snowshowers": ("눈", "🌨"),
    "rainandthunder": ("뇌우", "⛈"), "rainshowersandthunder": ("뇌우", "⛈"),
    "heavyrainandthunder": ("강한 뇌우", "⛈"), "sleetandthunder": ("뇌우", "⛈"),
    "snowandthunder": ("뇌우", "⛈"), "heavyrainshowersandthunder": ("강한 뇌우", "⛈"),
}


def wmo(code) -> tuple:
    """Met.no symbol_code (or None) → (한국어 label, emoji). Strips day/night suffix."""
    if not code or not isinstance(code, str):
        return ("—", "🌡")
    base = code.split("_")[0]
    return _SYM.get(base, ("—", "🌡"))


# ── Korean city curated table (inlined from kr_cities — not available in the plugin path) ──
# Each entry: (ko short-name, place display label, en alias, lat, lon)
_KR_RAW = [
    # 광역시도 + 세종
    ("서울", "서울특별시", "Seoul", 37.5665, 126.9780),
    ("부산", "부산광역시", "Busan", 35.1796, 129.0756),
    ("인천", "인천광역시", "Incheon", 37.4563, 126.7052),
    ("대구", "대구광역시", "Daegu", 35.8714, 128.6014),
    ("대전", "대전광역시", "Daejeon", 36.3504, 127.3845),
    ("광주", "광주광역시", "Gwangju", 35.1595, 126.8526),
    ("울산", "울산광역시", "Ulsan", 35.5384, 129.3114),
    ("세종", "세종특별자치시", "Sejong", 36.4801, 127.2890),
    # 경기
    ("수원", "수원시, 경기", "Suwon", 37.2636, 127.0286),
    ("성남", "성남시, 경기", "Seongnam", 37.4200, 127.1267),
    ("고양", "고양시, 경기", "Goyang", 37.6584, 126.8320),
    ("용인", "용인시, 경기", "Yongin", 37.2411, 127.1776),
    ("부천", "부천시, 경기", "Bucheon", 37.5034, 126.7660),
    ("안산", "안산시, 경기", "Ansan", 37.3219, 126.8309),
    ("안양", "안양시, 경기", "Anyang", 37.3943, 126.9568),
    ("남양주", "남양주시, 경기", "Namyangju", 37.6360, 127.2165),
    ("화성", "화성시, 경기", "Hwaseong", 37.1996, 126.8312),
    ("평택", "평택시, 경기", "Pyeongtaek", 36.9921, 127.1129),
    ("의정부", "의정부시, 경기", "Uijeongbu", 37.7380, 127.0337),
    ("파주", "파주시, 경기", "Paju", 37.7599, 126.7800),
    ("김포", "김포시, 경기", "Gimpo", 37.6152, 126.7156),
    ("시흥", "시흥시, 경기", "Siheung", 37.3800, 126.8029),
    ("광명", "광명시, 경기", "Gwangmyeong", 37.4786, 126.8644),
    ("군포", "군포시, 경기", "Gunpo", 37.3617, 126.9352),
    ("하남", "하남시, 경기", "Hanam", 37.5394, 127.2149),
    ("구리", "구리시, 경기", "Guri", 37.5943, 127.1296),
    ("오산", "오산시, 경기", "Osan", 37.1499, 127.0772),
    ("이천", "이천시, 경기", "Icheon", 37.2792, 127.4350),
    ("안성", "안성시, 경기", "Anseong", 37.0080, 127.2797),
    # 강원
    ("춘천", "춘천시, 강원", "Chuncheon", 37.8813, 127.7300),
    ("원주", "원주시, 강원", "Wonju", 37.3422, 127.9202),
    ("강릉", "강릉시, 강원", "Gangneung", 37.7519, 128.8761),
    ("속초", "속초시, 강원", "Sokcho", 38.2070, 128.5918),
    ("동해", "동해시, 강원", "Donghae", 37.5247, 129.1143),
    # 충북
    ("청주", "청주시, 충북", "Cheongju", 36.6424, 127.4890),
    ("충주", "충주시, 충북", "Chungju", 36.9910, 127.9259),
    ("제천", "제천시, 충북", "Jecheon", 37.1326, 128.1910),
    # 충남
    ("천안", "천안시, 충남", "Cheonan", 36.8151, 127.1139),
    ("아산", "아산시, 충남", "Asan", 36.7898, 127.0019),
    ("서산", "서산시, 충남", "Seosan", 36.7848, 126.4503),
    ("당진", "당진시, 충남", "Dangjin", 36.8897, 126.6457),
    ("공주", "공주시, 충남", "Gongju", 36.4466, 127.1190),
    # 전북
    ("전주", "전주시, 전북", "Jeonju", 35.8242, 127.1480),
    ("익산", "익산시, 전북", "Iksan", 35.9483, 126.9576),
    ("군산", "군산시, 전북", "Gunsan", 35.9678, 126.7368),
    ("정읍", "정읍시, 전북", "Jeongeup", 35.5700, 126.8560),
    ("남원", "남원시, 전북", "Namwon", 35.4161, 127.3897),
    # 전남
    ("순천", "순천시, 전남", "Suncheon", 34.9506, 127.4872),
    ("여수", "여수시, 전남", "Yeosu", 34.7604, 127.6622),
    ("목포", "목포시, 전남", "Mokpo", 34.8118, 126.3922),
    # 경북
    ("포항", "포항시, 경북", "Pohang", 36.0190, 129.3435),
    ("경주", "경주시, 경북", "Gyeongju", 35.8562, 129.2247),
    ("구미", "구미시, 경북", "Gumi", 36.1197, 128.3446),
    ("안동", "안동시, 경북", "Andong", 36.5684, 128.7294),
    # 경남
    ("창원", "창원시, 경남", "Changwon", 35.2279, 128.6811),
    ("진주", "진주시, 경남", "Jinju", 35.1798, 128.1076),
    ("김해", "김해시, 경남", "Gimhae", 35.2285, 128.8890),
    ("통영", "통영시, 경남", "Tongyeong", 34.8544, 128.4333),
    # 제주
    ("제주", "제주시, 제주", "Jeju", 33.4996, 126.5312),
    ("서귀포", "서귀포시, 제주", "Seogwipo", 33.2541, 126.5600),
]

_KR_CITIES = [
    {"ko": ko, "place": place, "en": en, "lat": lat, "lon": lon,
     "tz": "Asia/Seoul", "country_code": "KR", "population": 0, "rank": i}
    for i, (ko, place, en, lat, lon) in enumerate(_KR_RAW)
]


def _kr_search(q: str, limit: int = 6) -> list:
    """Korean city name → ranked candidate list from the local curated table."""
    s = (q or "").strip()
    if not s:
        return []
    low = s.lower()
    hits = []
    for c in _KR_CITIES:
        ko, en = c["ko"], c["en"].lower()
        if s in ko or en.startswith(low) or low in en:
            starts = ko.startswith(s) or en.startswith(low)
            hits.append((0 if starts else 1, c["rank"], c))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [c for _, _, c in hits[:limit]]


# ── config (location) ──────────────────────────────────────────────────────

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


def _get_json(url: str, params: dict, headers: dict = None, timeout: int = 15, attempts: int = 3):
    """GET+parse JSON with retries (transient 5xx/TLS drops → retry). None after all fail."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    hdrs = {"User-Agent": "OMPB/1.0"}
    if headers:
        hdrs.update(headers)
    for i in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=hdrs), timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception:  # noqa: BLE001 — best-effort
            if i < attempts - 1:
                time.sleep(1.2 * (i + 1))
    return None


def _rank_results(res: list) -> list:
    """Geocoding hits ranked for Korean users: KP(북한) last, then highest population first
    (real cities float above tiny same-named villages; None population → 0)."""
    return sorted(res, key=lambda x: (1 if x.get("country_code") == "KP" else 0, -(x.get("population") or 0)))


def _label(r: dict, fallback: str) -> str:
    """'name, admin1' (or 'name, country') display label, avoiding duplication."""
    name = r.get("name") or fallback
    if r.get("admin1") and r["admin1"] not in name:
        return f"{name}, {r['admin1']}"
    if r.get("country") and r.get("country") not in name:
        return f"{name}, {r['country']}"
    return name


def _candidate(r: dict, fallback: str) -> dict:
    """Open-Meteo result → our candidate shape (matches _KR_CITIES entries)."""
    return {"place": _label(r, fallback), "lat": r["latitude"], "lon": r["longitude"],
            "tz": r.get("timezone") or "auto", "country_code": r.get("country_code"),
            "population": r.get("population") or 0}


def geocode_candidates(place: str, limit: int = 6) -> list:
    """City name → ranked candidate list for autocomplete. Each candidate carries its own
    lat/lon/tz so the caller can store it directly (no re-geocode → no bare-name mis-match).
    Korean major cities resolve from the local curated table first (Open-Meteo can't match a bare
    Korean short name like '성남' to '성남시'); only uncovered/international queries hit Open-Meteo.
    Item: {place(label), lat, lon, tz, country_code, population}."""
    if not place or not place.strip():
        return []
    local = _kr_search(place, limit)
    if local:
        return [{k: c[k] for k in ("place", "lat", "lon", "tz", "country_code", "population")}
                for c in local]
    d = _get_json(_GEOCODE, {"name": place.strip(), "count": 10, "language": "ko"})
    res = _rank_results((d or {}).get("results") or [])
    return [_candidate(r, place.strip()) for r in res[:limit]
            if r.get("latitude") is not None and r.get("longitude") is not None]


def geocode(place: str) -> Optional[dict]:
    """City name → {lat, lon, place, tz}. None if not found. Korean major cities come from the
    local curated table (exact, avoids the bare-name mis-match); otherwise Open-Meteo with a
    populous-city-first / North-Korea-last ranking."""
    if not place or not place.strip():
        return None
    local = _kr_search(place, 1)
    if local:
        c = local[0]
        return {"lat": c["lat"], "lon": c["lon"], "place": c["place"], "tz": c["tz"]}
    d = _get_json(_GEOCODE, {"name": place.strip(), "count": 10, "language": "ko"})
    res = _rank_results((d or {}).get("results") or [])
    if not res:
        return None
    r = res[0]
    return {"lat": r["latitude"], "lon": r["longitude"], "place": _label(r, place),
            "tz": r.get("timezone") or "auto"}


def get_location(home: Optional[str]) -> Optional[dict]:
    """Resolved {lat, lon, place, tz}, or None. Reads config; if absent, tries the Strava athlete
    city (geocoded) once and caches it.

    Note: the plugin path has no Strava athlete-city helper yet (ompb-apps strava module is
    app-layer only). The strava lookup is wrapped in try/except so it degrades to None gracefully,
    and the caller falls back to manual location only."""
    if not home:
        return None
    cfg = _read_config(home)
    if cfg.get("wx_lat") is not None and cfg.get("wx_lon") is not None:
        return {"lat": cfg["wx_lat"], "lon": cfg["wx_lon"],
                "place": cfg.get("wx_place") or "", "tz": cfg.get("wx_tz") or "auto"}
    # Optional best-effort: try to get Strava athlete city (plugin path has no such helper yet).
    city = None
    try:
        from strava_connect import athlete_city  # type: ignore[import]
        city = athlete_city(home)
    except Exception:  # noqa: BLE001 — no strava helper in plugin path, treat as None
        city = None
    if city:
        loc = geocode(city)
        if loc:
            set_location(home, loc["place"], loc["lat"], loc["lon"], loc.get("tz"))
            return loc
    return None


def set_location(home: str, place: str, lat: float = None, lon: float = None,
                 tz: str = None) -> Optional[dict]:
    """Set the runner's location. With lat/lon → store; with only a place → geocode. Returns the
    stored {lat, lon, place, tz} or None if geocoding failed."""
    if lat is None or lon is None:
        loc = geocode(place)
        if not loc:
            return None
        lat, lon, place, tz = loc["lat"], loc["lon"], loc["place"], loc.get("tz")
    cfg = _read_config(home)
    cfg.update({"wx_lat": float(lat), "wx_lon": float(lon), "wx_place": place, "wx_tz": tz or "auto"})
    _write_config(home, cfg)
    try:
        os.remove(os.path.join(home, "weather.json"))   # location changed → invalidate cache
    except OSError:
        pass
    return {"lat": float(lat), "lon": float(lon), "place": place, "tz": tz or "auto"}


# ── derived metrics (Met.no gives T/RH/wind; we compute feels-like + dew point) ──

def _apparent_temp(t: Optional[float], rh: Optional[float], wind_ms: Optional[float]) -> Optional[float]:
    """Steadman apparent temperature (°C) from temp, humidity, wind — the 'feels-like' the heat
    pace adjustment uses. Falls back to plain temp if humidity is missing."""
    if t is None:
        return None
    if rh is None:
        return round(t, 1)
    e = (rh / 100.0) * 6.105 * math.exp(17.27 * t / (237.7 + t))  # vapour pressure (hPa)
    at = t + 0.33 * e - 0.70 * (wind_ms or 0) - 4.00
    return round(at, 1)


def _dew_point(t: Optional[float], rh: Optional[float]) -> Optional[float]:
    if t is None or rh is None or rh <= 0:
        return None
    g = math.log(rh / 100.0) + 17.27 * t / (237.7 + t)
    return round(237.7 * g / (17.27 - g), 1)


# ── forecast fetch + cache (Met.no + Open-Meteo air quality) ─────────────────

def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _local_date(iso_z: str, tz: str) -> str:
    """UTC ISO timestamp → local YYYY-MM-DD in tz (for per-day grouping that matches the calendar)."""
    try:
        from zoneinfo import ZoneInfo
        dt = _dt.datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        zone = ZoneInfo("Asia/Seoul" if tz in (None, "", "auto") else tz)
        return dt.astimezone(zone).date().isoformat()
    except Exception:  # noqa: BLE001
        return iso_z[:10]


def _parse(met: dict, aq: Optional[dict], tz: str) -> Optional[dict]:
    """Met.no timeseries (+ Open-Meteo air quality) → our {current, daily} schema."""
    series = (((met or {}).get("properties") or {}).get("timeseries")) or []
    if not series:
        return None
    aqc = (aq or {}).get("current") or {}

    # current = first timestep
    e0 = series[0].get("data") or {}
    inst = (e0.get("instant") or {}).get("details") or {}
    t, rh = inst.get("air_temperature"), inst.get("relative_humidity")
    wind_ms = inst.get("wind_speed")
    sym = ((e0.get("next_1_hours") or e0.get("next_6_hours") or {}).get("summary") or {}).get("symbol_code")
    precip1 = ((e0.get("next_1_hours") or {}).get("details") or {}).get("precipitation_amount")
    current = {
        "temp": t, "feels": _apparent_temp(t, rh, wind_ms), "humidity": rh,
        "dew_point": _dew_point(t, rh), "precip": precip1,
        "wind": round((wind_ms or 0) * 3.6, 1),   # m/s → km/h
        "code": sym,
        "pm25": aqc.get("pm2_5"), "pm10": aqc.get("pm10"), "us_aqi": aqc.get("us_aqi"),
    }

    # daily: group timesteps by local date
    by_day = {}
    for entry in series:
        date = _local_date(entry.get("time", ""), tz)
        d = entry.get("data") or {}
        det = (d.get("instant") or {}).get("details") or {}
        at = det.get("air_temperature")
        if at is None:
            continue
        feels = _apparent_temp(at, det.get("relative_humidity"), det.get("wind_speed"))
        precip6 = ((d.get("next_6_hours") or {}).get("details") or {}).get("precipitation_amount") or 0
        pop = ((d.get("next_1_hours") or d.get("next_6_hours") or {}).get("details") or {}).get("probability_of_precipitation")
        sc = ((d.get("next_6_hours") or d.get("next_1_hours") or {}).get("summary") or {}).get("symbol_code")
        hour = entry.get("time", "")[11:13]
        b = by_day.setdefault(date, {"date": date, "t_max": at, "t_min": at, "feels_max": feels,
                                     "precip": 0.0, "pop": 0, "wind_max": det.get("wind_speed") or 0,
                                     "code": sc, "_noon": None})
        b["t_max"] = max(b["t_max"], at)
        b["t_min"] = min(b["t_min"], at)
        if feels is not None:
            b["feels_max"] = max(b["feels_max"] if b["feels_max"] is not None else feels, feels)
        b["precip"] += precip6 if hour in ("00", "06", "12", "18") else 0  # 6h blocks, avoid double count
        if pop is not None:
            b["pop"] = max(b["pop"], pop)
        b["wind_max"] = max(b["wind_max"], det.get("wind_speed") or 0)
        if hour in ("12", "13", "14") and b["_noon"] is None:   # representative midday symbol
            b["code"] = sc or b["code"]; b["_noon"] = True

    daily = []
    for date in sorted(by_day)[:7]:
        b = by_day[date]
        # precip probability: use Met.no pop if present, else derive from amount
        prob = b["pop"] if b["pop"] else (70 if b["precip"] >= 1.0 else (40 if b["precip"] >= 0.2 else 0))
        daily.append({
            "date": date, "t_max": round(b["t_max"]), "t_min": round(b["t_min"]),
            "feels_max": round(b["feels_max"]) if b["feels_max"] is not None else None,
            "precip_prob": int(prob), "wind_max": round(b["wind_max"] * 3.6, 1),  # km/h
            "uv_max": None, "code": b["code"],
        })

    return {"fetched_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "current": current, "daily": daily}


def _fetch_fresh(lat: float, lon: float, tz: str = "auto") -> Optional[dict]:
    met = _get_json(_MET, {"lat": round(lat, 4), "lon": round(lon, 4)}, headers={"User-Agent": _MET_UA})
    if not met:
        return None
    aq = _get_json(_AIR, {"latitude": lat, "longitude": lon, "timezone": "auto",
                          "current": "pm2_5,pm10,us_aqi"})
    return _parse(met, aq, tz)


def forecast(home: Optional[str], *, force: bool = False) -> Optional[dict]:
    """Cached forecast for the runner's location, refreshed past TTL. None if no location/unreachable.
    Best-effort: a fetch failure falls back to stale cache if present."""
    loc = get_location(home)
    if not loc:
        return None
    path = os.path.join(home, "weather.json")
    cached = None
    if os.path.isfile(path) and not force:
        try:
            with open(path, encoding="utf-8") as fh:
                cached = json.load(fh)
            ts = _dt.datetime.strptime(cached["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
            if (_now() - ts).total_seconds() < _TTL_S:
                cached["place"] = loc["place"]
                return cached
        except Exception:  # noqa: BLE001
            cached = None
    fresh = _fetch_fresh(loc["lat"], loc["lon"], loc.get("tz") or "auto")
    if fresh:
        fresh["place"] = loc["place"]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(fresh, fh, ensure_ascii=False)
        except OSError:
            pass
        return fresh
    if cached:
        cached["place"] = loc["place"]
    return cached


# ── running advice (deterministic) ───────────────────────────────────────────

def heat_pace_adjust(feels_c: Optional[float]) -> int:
    """Seconds/km to ADD for heat, from feels-like temp. ~0 below 15°C, ~2.5s/°C, capped 60."""
    if feels_c is None or feels_c <= 15:
        return 0
    return int(min(60, round((feels_c - 15) * 2.5)))


def aqi_band(pm25: Optional[float], us_aqi: Optional[float]) -> Optional[dict]:
    if pm25 is None and us_aqi is None:
        return None
    a = us_aqi if us_aqi is not None else 0
    p = pm25 if pm25 is not None else 0
    if a >= 151 or p >= 55:
        return {"level": "unhealthy", "ko": "나쁨", "advice": "실내 트레드밀 권장 · 야외면 강도 낮추고 마스크"}
    if a >= 101 or p >= 35:
        return {"level": "usg", "ko": "민감군 주의", "advice": "고강도는 피하고 이지로 · 호흡기 민감하면 실내"}
    if a >= 51 or p >= 16:
        return {"level": "moderate", "ko": "보통", "advice": "대체로 괜찮아요 · 장시간 고강도는 약간 주의"}
    return {"level": "good", "ko": "좋음", "advice": "공기 깨끗 — 마음껏 달리기 좋아요"}


def _comfort(feels: Optional[float]) -> str:
    if feels is None:
        return ""
    if feels >= 30:
        return "무더위"
    if feels >= 24:
        return "더움"
    if feels >= 10:
        return "쾌적"
    if feels >= 0:
        return "쌀쌀"
    return "추위"


def advise(day: dict, workout_type: str = "") -> dict:
    """Running advice for a day (current or daily) + optional workout type."""
    feels = day.get("feels") if "feels" in day else day.get("feels_max")
    adj = heat_pace_adjust(feels)
    aq = aqi_band(day.get("pm25"), day.get("us_aqi"))
    flags = []
    hard = workout_type in ("interval", "tempo", "race")
    if adj >= 25 and hard:
        flags.append("더위+하드세션 — 이른 아침/저녁, 강도↓ 또는 요일 스왑 고려")
    elif adj >= 25:
        flags.append(f"더위 — 페이스 +{adj}초/km 여유, 수분 보충")
    elif adj > 0:
        flags.append(f"페이스 +{adj}초/km 여유")
    if aq and aq["level"] in ("unhealthy", "usg"):
        flags.append(f"미세먼지 {aq['ko']} — {aq['advice']}")
    if (day.get("precip_prob") or 0) >= 60:
        flags.append("비 가능성 높음 — 우중런 대비/실내 대안")
    if (day.get("wind_max") or day.get("wind") or 0) >= 30:
        flags.append("강풍 — 맞바람 구간 페이스 여유")
    note = " · ".join(flags) if flags else "달리기 좋은 컨디션"
    return {"comfort": _comfort(feels), "pace_adjust_s": adj, "aqi": aq, "flags": flags, "note": note}


def summary_line(home: Optional[str]) -> Optional[str]:
    """One-line weather+advice for coach grounding / compact display. None if no weather."""
    wx = forecast(home)
    if not wx:
        return None
    c = wx.get("current") or {}
    label, _ = wmo(c.get("code"))
    adv = advise(c)
    bits = [f"{wx.get('place','')} {label} {round(c['temp']) if c.get('temp') is not None else '?'}°C"]
    if c.get("feels") is not None and abs((c.get("feels") or 0) - (c.get("temp") or 0)) >= 2:
        bits.append(f"체감 {round(c['feels'])}°C")
    if adv["aqi"]:
        bits.append(f"미세먼지 {adv['aqi']['ko']}")
    if adv["flags"]:
        bits.append(adv["note"])
    return " · ".join(bits)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="weather.py",
        description="OMPB weather toolkit — forecast lookup and location management.",
    )
    ap.add_argument("--home", help="Explicit OMPB_HOME override.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("forecast", help="Print JSON forecast for the resolved home location.")

    sloc = sub.add_parser("set-location", help="Persist a location to config.json.")
    sloc.add_argument("--place", required=True, help="City name (geocoded if lat/lon omitted).")
    sloc.add_argument("--lat", type=float, default=None, help="Latitude (optional).")
    sloc.add_argument("--lon", type=float, default=None, help="Longitude (optional).")
    sloc.add_argument("--tz", default=None, help="IANA timezone (optional).")

    args = ap.parse_args(argv)
    home = resolve_home(args.home)

    if args.cmd == "forecast":
        wx = forecast(home)
        if wx:
            print(json.dumps(wx, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "no location set or forecast unavailable"}, ensure_ascii=False))
    elif args.cmd == "set-location":
        result = set_location(home, args.place, args.lat, args.lon, args.tz)
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": f"geocoding failed for: {args.place}"}, ensure_ascii=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
