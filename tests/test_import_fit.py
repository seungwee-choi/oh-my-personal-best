"""Unit tests for .fit import: the start-time dedup fingerprint (scripts/import_fit.py).

The bug these lock: FIT entries carried no ``started_at``, so entry_fingerprint() fell back to
its ``('d', date, distance)`` form while Strava entries always produce the ``('t', sport, minute)``
form. dup_kind() branches on that form, so the two could never match — one runner who connected
Strava and then bulk-imported COROS .fit files got their entire history twice (1620 strava +
1609 fit entries, 1432 twin pairs at identical distances).

These tests drive real .fit *binary* through fitdecode (build_fit_file below writes a valid FIT
file — header, definition + data message, CRC) rather than a mocked message object, so a
fitdecode field-name or value-type change surfaces here instead of passing on a stub.

Run: `python3 tests/test_import_fit.py`  (needs fitdecode; otherwise stdlib only.)
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import import_fit as imp  # noqa: E402
import import_strava as imp_strava  # noqa: E402
import ompb_env  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


# ---------------------------------------------------------------------------
# Minimal FIT file writer (real binary — fitdecode parses it for real)
# ---------------------------------------------------------------------------

FIT_UTC_REFERENCE = 631065600  # FIT date_time epoch: 1989-12-31T00:00:00Z

_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)

# session (global msg 18) fields: (field_def_num, base_type, size, pack format)
_SESSION_FIELDS = (
    (253, 0x86, 4, "<I"),  # timestamp        date_time
    (2,   0x86, 4, "<I"),  # start_time       date_time  <- the field under test
    (5,   0x00, 1, "<B"),  # sport            enum (1 = running)
    (9,   0x86, 4, "<I"),  # total_distance   uint32, scale 100 -> cm
    (8,   0x86, 4, "<I"),  # total_timer_time uint32, scale 1000 -> ms
)


def _crc16(data):
    """FIT's CRC-16 (nibble table, low nibble first) — an invalid CRC makes fitdecode warn."""
    crc = 0
    for byte in data:
        for nibble in (byte & 0xF, (byte >> 4) & 0xF):
            tmp = _CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ _CRC_TABLE[nibble]
    return crc


def build_fit_file(epoch, distance_km=10.0, duration_s=3000, sport=1, source_id="12345"):
    """Write a one-session .fit file starting at POSIX `epoch`; return (path, source_id)."""
    fit_ts = int(epoch) - FIT_UTC_REFERENCE
    defn = bytearray((0x40, 0x00, 0x00))          # definition msg, local type 0, reserved, LE
    defn += struct.pack("<H", 18)                 # global msg num: session
    defn.append(len(_SESSION_FIELDS))
    for fnum, base_type, size, _ in _SESSION_FIELDS:
        defn += bytes((fnum, size, base_type))

    data = bytearray((0x00,))                     # data msg, local type 0
    values = (fit_ts, fit_ts, sport,
              int(round(distance_km * 1000 * 100)), int(round(duration_s * 1000)))
    for (_, _, _, fmt), val in zip(_SESSION_FIELDS, values):
        data += struct.pack(fmt, val)

    records = bytes(defn) + bytes(data)
    blob = struct.pack("<BBHI4s", 12, 0x10, 2140, len(records), b".FIT") + records
    blob += struct.pack("<H", _crc16(blob))

    path = os.path.join(tempfile.mkdtemp(prefix="ompb_test_fit_"), f"{source_id}.fit")
    with open(path, "wb") as fh:
        fh.write(blob)
    return path, source_id


def fit_entry(epoch, distance_km=10.0, tz=None, source_id="12345", **kw):
    """The entry import_fit would append to the log for a run starting at `epoch`."""
    path, sid = build_fit_file(epoch, distance_km=distance_km, source_id=source_id, **kw)
    entries = list(imp.parse_fit(path, sid, tz, 19.0))
    assert len(entries) == 1, f"expected one session entry, got {len(entries)}"
    return entries[0]


def strava_entry(started_at, distance_km=10.0, activity_id=999):
    """The entry import_strava would append for the same run, via the real to_entry()."""
    return imp_strava.to_entry({
        "id": activity_id, "type": "Run", "start_date": started_at,
        "start_date_local": started_at, "distance": distance_km * 1000,
        "moving_time": 3000, "start_latlng": [37.5, 127.0],
    }, 19.0)


def _seen():
    return {"ids": set(), "prints": set()}


EPOCH = 1780000000  # 2026-05-28T20:26:40Z


# ---------------------------------------------------------------------------
# The fix: FIT entries carry a start instant, in Strava's exact format
# ---------------------------------------------------------------------------

def test_started_at_is_the_utc_start_instant():
    entry = fit_entry(EPOCH)
    assert entry["started_at"] == "2026-05-28T20:26:40Z"


def test_started_at_format_matches_strava_byte_for_byte():
    # Not just "both parse" — the two writers must emit the same shape, since a format drift
    # would only show up as silently-missed dedup in production.
    fit = fit_entry(EPOCH)["started_at"]
    strava = strava_entry("2026-05-28T20:26:40Z")["started_at"]
    assert fit == strava, (fit, strava)


def test_started_at_is_utc_not_local_time():
    # Passing --tz must move the calendar `date` only. If started_at drifted to local time the
    # fingerprint would land 9 buckets*60 away from the Strava twin's and dedup would miss.
    if ZoneInfo is None:  # pragma: no cover
        return
    entry = fit_entry(EPOCH, tz=ZoneInfo("Asia/Seoul"))
    assert entry["date"] == "2026-05-29"          # KST is UTC+9: past midnight
    assert entry["started_at"] == "2026-05-28T20:26:40Z"


def test_fingerprint_is_time_form_not_distance_form():
    fp = ompb_env.entry_fingerprint(fit_entry(EPOCH))
    assert fp[0] == "t", fp                       # ('d', ...) can never match a Strava entry
    assert fp[1] == "running"                     # sport is part of the key — must match too


def test_every_fit_entry_gets_a_start_instant():
    # date and started_at are derived from the same field under the same isinstance guard, so
    # an entry that made it onto the calendar always has the instant too — no 'd'-form leaks.
    for epoch in (EPOCH, EPOCH + 37, 1600000000):
        entry = fit_entry(epoch)
        assert entry["date"] and entry.get("started_at"), entry


# ---------------------------------------------------------------------------
# Cross-source dedup: the actual production symptom
# ---------------------------------------------------------------------------

def test_fit_run_collapses_into_its_strava_twin():
    # The reported bug, both directions: Strava synced first, then the .fit bulk import.
    seen = _seen()
    ompb_env.mark_seen(seen, strava_entry("2026-05-28T20:26:40Z"))
    assert ompb_env.dup_kind(seen, fit_entry(EPOCH)) == "cross-source"


def test_strava_sync_after_fit_import_also_collapses():
    seen = _seen()
    ompb_env.mark_seen(seen, fit_entry(EPOCH))
    assert ompb_env.dup_kind(seen, strava_entry("2026-05-28T20:26:40Z")) == "cross-source"


def test_twins_collapse_despite_different_gps_distances():
    # The two sources measure the run slightly differently (2.154 vs 2.150 km) and have
    # different source_ids; only the shared start instant links them.
    seen = _seen()
    ompb_env.mark_seen(seen, strava_entry("2026-05-28T20:26:40Z", distance_km=2.154))
    assert ompb_env.dup_kind(seen, fit_entry(EPOCH, distance_km=2.150)) == "cross-source"


def test_twins_collapse_across_a_minute_bucket_edge():
    # Watch and phone clocks differ by a second that straddles :59 -> :00.
    seen = _seen()
    ompb_env.mark_seen(seen, strava_entry("2026-05-28T20:26:59Z"))
    assert ompb_env.dup_kind(seen, fit_entry(1780000020)) == "cross-source"  # 20:27:00Z


def test_distinct_same_day_sessions_are_not_merged():
    # The guard against over-merging: a morning and an evening 10 km are two runs, and the
    # time form must keep them apart (the old distance form would have merged them).
    import datetime as dt
    seen = _seen()
    morning = fit_entry(EPOCH - 36000, tz=dt.timezone.utc, source_id="A")  # 10:26:40Z
    evening = fit_entry(EPOCH, tz=dt.timezone.utc, source_id="B")          # 20:26:40Z
    assert morning["date"] == evening["date"] == "2026-05-28"
    ompb_env.mark_seen(seen, morning)
    assert ompb_env.dup_kind(seen, evening) is None


def test_reimporting_the_same_fit_file_is_still_id_deduped():
    seen = _seen()
    entry = fit_entry(EPOCH, source_id="COROS-1")
    ompb_env.mark_seen(seen, entry)
    assert ompb_env.dup_kind(seen, entry) == "id"


# ---------------------------------------------------------------------------
# Migration: logs already holding pre-fix FIT entries (no started_at, so 'd' form)
# ---------------------------------------------------------------------------

def _legacy(entry):
    """What the pre-fix importer wrote for this same run — everything but started_at."""
    return {k: v for k, v in entry.items() if k != "started_at"}


def test_reimport_over_a_prefix_log_is_still_caught_by_source_id():
    # Existing users' logs hold 'd'-form FIT entries, which a new 't'-form entry cannot match
    # by fingerprint. source_id is checked first in dup_kind, so re-importing the same .fit
    # files after the fix does NOT duplicate them.
    entry = fit_entry(EPOCH, source_id="COROS-1")
    seen = _seen()
    ompb_env.mark_seen(seen, _legacy(entry))
    assert ompb_env.dup_kind(seen, entry) == "id"


def test_known_gap_prefix_entry_vs_renamed_reexport():
    # The one case the form change makes worse, recorded deliberately rather than discovered
    # later: the same run re-exported under a DIFFERENT filename over a pre-fix log. Both
    # entries were 'd' form before, so they matched; now the new one is 't' form and the old
    # one is 'd', so neither source_id nor fingerprint links them. COROS/Garmin name .fit files
    # by stable activity id, so this needs a genuine re-export to hit — but it is not covered.
    entry = fit_entry(EPOCH, source_id="COROS-1")
    seen = _seen()
    ompb_env.mark_seen(seen, _legacy(entry))
    assert ompb_env.dup_kind(seen, dict(entry, source_id="COROS-RENAMED")) is None


# ---------------------------------------------------------------------------
# _utc_iso: never invent an instant
# ---------------------------------------------------------------------------

def test_utc_iso_returns_none_for_a_missing_or_raw_value():
    # fitdecode leaves pre-1998 date_time values as raw ints, and the field can be absent.
    # Both must yield None so the entry keeps the legacy fingerprint instead of a wrong bucket.
    assert imp._utc_iso(None) is None
    assert imp._utc_iso(0) is None
    assert imp._utc_iso(1780000000) is None
    assert imp._utc_iso("2026-05-28T20:26:40Z") is None


def test_utc_iso_treats_a_naive_datetime_as_utc():
    import datetime as dt
    naive = dt.datetime(2026, 5, 28, 20, 26, 40)
    assert imp._utc_iso(naive) == "2026-05-28T20:26:40Z"


def test_utc_iso_converts_a_non_utc_datetime_to_utc():
    import datetime as dt
    kst = dt.timezone(dt.timedelta(hours=9))
    aware = dt.datetime(2026, 5, 29, 5, 26, 40, tzinfo=kst)
    assert imp._utc_iso(aware) == "2026-05-28T20:26:40Z"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("import_fit: all tests passed")
