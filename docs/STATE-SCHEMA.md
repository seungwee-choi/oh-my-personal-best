# State Schema

OMPB persists runner state under OMPB_HOME (smart-resolved $OMPB_HOME -> ~/.ompb -> ./.ompb). All agents read/write through these
shapes. Times are stored as `HH:MM:SS` or `MM:SS` strings; paces as `MM:SS` per km.

## `runner-profile.json`
```json
{
  "name": "string",
  "age": 0,
  "sex": "M | F | other | unspecified",
  "weight_kg": 0,
  "weekly_mileage_km": 0,
  "experience": "beginner | intermediate | advanced",
  "current_pb": {
    "10k": "MM:SS",
    "half": "H:MM:SS",
    "full": "H:MM:SS"
  },
  "injury_history": ["string"],
  "updated_at": "ISO-8601"
}
```

## `goal.json`
```json
{
  "event": "10k | half | full",
  "target_time": "H:MM:SS",
  "race_date": "YYYY-MM-DD",
  "race_date_estimated": false,
  "race_date_note": "string",
  "weeks_remaining": 0,
  "race_name": "string",
  "created_at": "ISO-8601"
}
```
- `race_date_estimated`: `true` when the date is inferred (official date unannounced), `false` when confirmed. `weeks_remaining` and the peak/taper placement depend on it.
- `race_date_note`: free text, e.g. "estimated: 4th Sunday of October — re-align when official". When the date is confirmed, set `race_date`, flip `race_date_estimated` to `false`, recompute `weeks_remaining`, and re-run the plan (plan-critic re-gate).

## `training-log.jsonl` (append-only, one JSON object per line)
```json
{"date":"YYYY-MM-DD","type":"easy|long|tempo|interval|recovery|race|cross|rest","planned":{"distance_km":0,"pace":"MM:SS","notes":"string"},"actual":{"distance_km":0,"pace":"MM:SS","avg_hr":0,"max_hr":0,"cadence":0,"rpe":0,"duration_s":0,"calories":0,"ascent_m":0,"notes":"string"},"sport":"running|cycling|swimming|walking|hiking|other","source":"csv|nl|api|fit","source_id":"string","logged_at":"ISO-8601"}
```
- `rpe`: rate of perceived exertion, 1–10.
- `source`: how the entry arrived — `csv`/`nl`/`api`, or `fit` (Garmin/COROS .fit import).
- `source_id`: stable id for the source activity (the .fit filename stem for COROS). Used to de-duplicate re-imports — an entry whose `source_id` already exists in the log is skipped.
- `sport`: the recorded activity sport. Running maps to a running `type` (easy/long/…); every other sport is recorded with `type: "cross"` so total training load is captured. For non-running, `pace` and `cadence` are `null` (they are not comparable to running).
- `type` refinement: importers can only see distance, so they type runs coarsely (`easy`/`long`). `scripts/reclassify.py` (also `ompb_core.reclassify`) re-types running sessions into `recovery | easy | tempo | interval | long` using HR/pace bands **calibrated to the runner** (see `scripts/classify.py`) — recovery = low HR + slow + short, tempo = sustained high HR (steady), interval = high peak HR with a big avg→max spread. Idempotent; re-run after imports (calibration sharpens as the log grows). `race` is never auto-inferred.
- `type_source` (optional): marks a high-confidence type that `reclassify.py` must NOT overwrite. `"name"` = from an explicit activity name/title keyword (CSV or Strava). `"strava"` = from Strava's structured `workout_type` tag (1→race, 2→long run, 3→workout; the workout tag is only applied when HR is absent, otherwise HR refinement decides tempo↔interval). Entries without `type_source` are re-derived from metrics.
- `reclassified_from_sport` (optional): present only when the importer reclassified an untagged `generic` activity into running based on running evidence (foot dynamics or a 2:30–9:00/km pace). Value is the original sport (`"generic"`). Lets analysis agents treat such entries as slightly lower-confidence.
- `duration_s`, `calories`, `ascent_m`: optional enrichment from device imports (FIT). Absent fields are `null`.
- A planned-but-not-done session has `actual: null` (missed); an unplanned session has `planned: null`.

## `pb-history.json`
```json
{
  "entries": [
    {"event": "10k|half|full", "time": "H:MM:SS", "date": "YYYY-MM-DD", "race_name": "string"}
  ]
}
```

## `plan-state.json`
```json
{
  "phase": "base | build | peak | taper",
  "plan_week": 0,
  "total_weeks": 0,
  "this_week_target_km": 0,
  "key_sessions": ["string"],
  "last_adapted": "ISO-8601",
  "critic_approved": true
}
```

## `plan-week.json` (current week's PLAN_DATA — written by session-coach, rendered by build_week.py)
```json
{
  "athlete": "string",
  "today": "YYYY-MM-DD",
  "goal": {
    "event": "10k | half | full",
    "target_time": "H:MM:SS",
    "race_date": "YYYY-MM-DD",
    "weeks_to_race": 0
  },
  "week": {
    "plan_week": 0,
    "total_weeks": 0,
    "phase": "base | build | peak | taper",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "target_km": 0,
    "prev_week_km": 0,
    "ramp_pct": 0,
    "focus": "string"
  },
  "days": [
    {
      "dow": "Mon | Tue | Wed | Thu | Fri | Sat | Sun",
      "date": "YYYY-MM-DD",
      "type": "easy | long | tempo | interval | recovery | rest | cross",
      "title": "string",
      "distance_km": 0,
      "pace": "MM:SS",
      "hr_zone": 0,
      "structure": "string",
      "purpose": "string",
      "done": false
    }
  ],
  "coach_notes": ["string"],
  "critic_approved": true
}
```
- `type` ∈ `easy | long | tempo | interval | recovery | rest | cross` (matches `training-log.jsonl`).
- `summary` (total weekly km, sessions count) is auto-computed by `build_week.py` if absent.
- Overwritten each time `session-coach` produces a fresh weekly plan; the rendered HTML is written to `$OMPB_HOME/weeks/`.

## `diagnosis.json` (optional — written by race-analyst, consumed by pb-report)
```json
{
  "summary": "one-paragraph plain-language overview of the training picture",
  "limiter": "the #1 limiting factor (e.g. threshold endurance, speed, durability)",
  "feasibility": "goal realism verdict + one-line rationale (omit if no goal set)",
  "observations": ["evidence-backed observation", "..."],
  "generated_at": "ISO-8601"
}
```
- `summary`, `limiter`, and `feasibility` MUST be plain strings. `observations` MUST be a list of strings. Downstream renderers (`build_report.py`) perform string operations on all four fields — writing any of them as a nested object or list will cause rendering errors.
- If richer structure is useful, put it under an optional `detail` object key. Never make the three core fields objects.

## `injuries.jsonl` (injury episodes — one episode per line, append/atomic-rewrite)
Owned by `scripts/injury.py` (`ompb_core.injury_*`). The coach *advises* but this module is the
single writer — capture is conservative (`injury_parse` only PROPOSES from text that has both a
body-part token and a pain cue; the coach confirms before `injury_create` persists). Each episode
carries a deterministic **return-to-run phase ladder** that the plan guardrail reads.
```json
{"id":"inj-<hex>","body_part":"knee|achilles|calf|hamstring|itb|shin|plantar|foot|hip|ankle|quad|glute|back","side":"left|right|both|null","label":"string","onset_date":"YYYY-MM-DD","severity":0,"status":"active|recovering|resolved","phase":"rest|walk|walk_run|easy_only|build|full","load_cap_pct":0,"notes":[{"date":"YYYY-MM-DD","text":"string"}],"checkins":[{"date":"YYYY-MM-DD","pain_during":0,"pain_after":0,"ran":false}],"onset_run_id":"string|null","resolved_date":"YYYY-MM-DD|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```
- `phase` ladder: `rest → walk → walk_run → easy_only → build → full`. Each phase has a `load_cap_pct` (0/0/30/50/80/100) and an allowed-workout-type set. Two clean (`pain ≤ 2`) consecutive *running* check-ins advance one phase; a flare (`pain ≥ 6`) steps back one. `full` = no restriction.
- `injury_snapshot(home)` folds all open episodes into one view (`load_cap_pct` = the lowest cap, `allowed_types` = the intersection of open phases) so the plan guardrail combines concurrent injuries to the most restrictive. `injured_dates(home, start, end)` lets the weekly calendar mark a session missed *during* an injury as recovery, not a penalised skip.
- **Safety:** a pain/injury signal routes to `physio-advisor` first; an active episode caps weekly load and restricts workout types in any plan `plan-architect`/`session-coach` produce.

## `body.jsonl` (weight + fueling log — one entry per line)
Owned by `scripts/body.py` (`ompb_core.log_weight` / `body_trend` / `body_summary`). Weight entries
and (optionally) per-session fueling notes.
```json
{"date":"YYYY-MM-DD","weight_kg":0,"bodyfat_pct":0,"note":"string","source":"nl|web|api","logged_at":"ISO-8601"}
```
- `body_trend` reports current weight, 7/30-day moving averages, and the kg/week rate; the safe-loss guard flags a rate faster than ~1%/week of bodyweight. `body_summary` bundles trend + race-weight gap + an under-fueling signal for `fuel-advisor` context.
- The race-weight **target** is stored as `target_weight_kg` in `goal.json` (merged in, never clobbering the race goal), not here.

## `strava.json` (Strava credentials — secrets, never commit)
Written by `scripts/strava_connect.py` after the one-time OAuth flow; read and updated (access token refresh) by `scripts/import_strava.py`. File permissions are set to 600 by the connect script.

```json
{
  "client_id": "string",
  "client_secret": "string",
  "refresh_token": "string",
  "access_token": "string",
  "expires_at": 0,
  "athlete_id": 0,
  "connected_at": "ISO-8601"
}
```

- `access_token` / `expires_at`: the short-lived (6-hour) bearer token; `import_strava.py` refreshes it automatically before each sync.
- `athlete_id`: the Strava athlete id, used for logging/debugging only.
- **This file contains secrets. It is gitignored with the rest of `$OMPB_HOME`. Never commit it.**
- Training-log entries imported from Strava carry `source: "strava"` and `source_id: "strava-<activityId>"` for deduplication.

## `reports/` (generated artifacts)
`scripts/build_report.py` writes comprehensive athlete report HTML to `$OMPB_HOME/reports/report-<YYYY-MM-DD>.html`.
Each report is print/PDF-ready and fully self-contained (no external dependencies). Rendered from vendored templates
(`templates/report.html` for English, `templates/report.ko.html` for Korean) that ship with the plugin and carry a
`__REPORT_DATA__` placeholder that `build_report.py` fills at render time. These are derived outputs; they are
gitignored with the rest of `$OMPB_HOME`.

## `weeks/` (generated artifacts)
`scripts/build_week.py` writes rendered weekly-plan cards to `$OMPB_HOME/weeks/week-<YYYY-MM-DD>.html`.
Each card is self-contained and one-page printable (no external dependencies). Rendered from vendored templates
(`templates/week.html` for English, `templates/week.ko.html` for Korean) with a `__PLAN_DATA__` placeholder
that `build_week.py` fills at render time. These are derived outputs; they are gitignored with the rest of `$OMPB_HOME`.

## `plans/` (versioned plan snapshots)
When plan-critic approves a plan, the orchestrator writes a timestamped snapshot to
`$OMPB_HOME/plans/plan-<YYYY-MM-DD>.json`. These files are never overwritten, so the full
history of every approved plan is retained.

## `weather.json` (forecast cache — derived, 2h TTL)
Written by `scripts/weather.py` (`ompb_core.weather_forecast`). A short-lived cache of the Met.no
forecast + Open-Meteo air-quality response for the runner's saved location, so repeated coaching
turns within 2 hours don't re-hit the network. Invalidated on a location change. Derived output;
gitignored with the rest of `$OMPB_HOME`. Never the source of truth — re-fetched on expiry.

## `config.json` (app settings)
```json
{ "language": "en", "hrmax": 0, "wx_place": "string", "wx_lat": 0, "wx_lon": 0, "wx_tz": "string" }
```
- `language`: `en` | `ko` (default `en`). Set at `/pb-setup`; drives both communication language and the `--lang` of generated artifacts (report, weekly card). Resolution: explicit `--lang` flag → `config.json` `language` → `en`. The runner can change it anytime ("한국어로" / "use English").
- `hrmax` (optional): a manual HRmax override. When present, the core's analysis and `ompb_core.zones` use it instead of the estimated HRmax for zone boundaries. Set via `ompb_core.set_hrmax` / cleared via `clear_hrmax` (the runner: "내 HRmax는 190이야").
- `wx_place` / `wx_lat` / `wx_lon` / `wx_tz` (optional): the runner's cached weather location (resolved once from a manual entry, geocoded). Read by `weather_forecast`; set by `weather_set_location`. Changing it invalidates `weather.json`.
- A home for future settings (units km/mi, timezone, …).

## Conventions
- `critic_approved` MUST be `true` before a plan is shown to the runner. `plan-critic` sets it.
- Weekly volume ramp is capped at ~10%/week unless `plan-critic` explicitly approves an exception.
- `data-logger` is the only writer of `training-log.jsonl`; it normalizes all input sources here.
- If `runner-profile.json` is absent, treat the runner as new and collect the minimum fields first.
