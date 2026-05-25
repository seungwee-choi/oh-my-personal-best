---
name: pb-setup
description: First-run onboarding — set up OMPB, import data, bootstrap profile, deliver first value
argument-hint: "[path to a COROS/Garmin export folder, .fit/.zip, or .csv]"
level: 4
---

<Purpose>
pb-setup is the single entry point a new user runs right after installing the plugin. It takes
someone from "just installed, nothing set up" to "first diagnosis + visual deck" in one guided
flow: it resolves paths, checks dependencies, imports the runner's data, bootstraps their profile
from that data, optionally captures a goal, and produces the first analysis deck. Everything else
(`/pb-today`, `/pb-log`, `/pb-deck`, `/pb-plan`) becomes useful only after this runs once.
</Purpose>

<Use_When>
- The runner just installed the plugin, or asks "how do I start / set up / get started / 시작"
- `OMPB_HOME` has no `training-log.jsonl` yet (no data imported)
- `runner-profile.json` is missing
- Keyword triggers: "setup", "get started", "온보딩", "시작하기", "처음", "first run"
</Use_When>

<Do_Not_Use_When>
- The runner is already set up (profile + log exist) and just wants a normal action — route to the specific command/skill instead.
</Do_Not_Use_When>

<Conventions>
- **Scripts** live in the installed plugin and MUST be invoked by absolute path:
  `python3 "$CLAUDE_PLUGIN_ROOT/scripts/<name>.py" ...`. Never assume `scripts/` is in the cwd.
- **Data** lives under `OMPB_HOME`, smart-resolved by the scripts: `$OMPB_HOME` → `~/.ompb` →
  `./.ompb` → default `~/.ompb`. Resolve it once at the start and tell the runner which dir is in use.
</Conventions>

<Steps>

## Step 0 — Resolve paths
Confirm `$CLAUDE_PLUGIN_ROOT` is set (it is, inside an installed plugin). Determine the data home:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/ompb_env.py" --print-home   # or: import resolve_home
```
Report to the runner: "Scripts: $CLAUDE_PLUGIN_ROOT/scripts · Data home: <resolved>". If they want a
specific location, they can `export OMPB_HOME=~/.ompb` before continuing.

## Step 0b — Language
Ask the runner's preferred language for communication and reports: **English or 한국어**. Write it
to `$OMPB_HOME/config.json` as `{"language": "en"}` or `{"language": "ko"}` (default `en` if they
don't care). From here on, respond in that language; report/weekly-card rendering picks it up via
`--lang` automatically. The runner can change it later by saying "한국어로" / "use English".

## Step 1 — Dependency check
`.fit` import needs `fitdecode`. Check:
```
python3 -c "import fitdecode" 2>/dev/null && echo OK || echo MISSING
```
If MISSING and the runner has `.fit` data, offer to install:
```
python3 -m pip install -r "$CLAUDE_PLUGIN_ROOT/requirements.txt"
```
CSV and natural-language paths need no extra dependency — skip this if the runner isn't importing `.fit`.

## Step 2 — Import data
Ask what the runner has (or use `$ARGUMENTS` if a path was given):
- **COROS / Garmin export** (folder, `.fit`, or `.zip`):
  `python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_fit.py" "<path>" --tz <local-tz>`
- **CSV export** (Strava etc.): `python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_csv.py" "<file.csv>"`
- **Strava account:** run `/pb-connect-strava` (one-time app + OAuth), then
  `python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_strava.py"` syncs all activities.
- **Nothing yet / log manually**: skip import; they can `/pb-log "ran 10K in 50:00"` later.
The importers append to `<home>/training-log.jsonl` (validated, deduped by `source_id`). Report the
summary (activities imported, by sport).

## Step 3 — Bootstrap the profile
Derive a `runner-profile.json` proposal from the imported log (delegate to `data-logger`):
- `current_pb` (10k/half/full) from the fastest clean efforts at each distance
- `weekly_mileage_km` from the median of recent weeks
- detect race-type efforts → seed `pb-history.json`
Present the derived values and ask the runner to confirm/correct age, sex, experience, injury history.
Write `runner-profile.json` (and `pb-history.json`) to `OMPB_HOME`.

## Step 4 — Goal (optional)
Ask if they're training for a race: event (10k/half/full), target time, race date. If yes, write
`goal.json`. If not, skip — diagnosis still works without a goal.

## Step 5 — Deliver first value
- `race-analyst` analyzes the log (+ profile/goal) → write `diagnosis.json` to `OMPB_HOME`.
- Render the deck: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_deck.py" --tz <local-tz>`.
- Report the deck path and offer to open it (`open <path>` on macOS).

## Step 6 — Show the core loop
Tell the runner what to do next:
- `/pb-today` — today's session · `/pb-log <path|text>` — log a run · `/pb-deck` — refresh the deck
- `/pb-plan "<goal>"` — build a periodized plan · "review my week" — weekly adaptation

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset (not running as an installed plugin) → tell the runner to install the plugin or run scripts from the repo with `python3 scripts/...`.
- fitdecode missing and the runner declines to install → fall back to CSV / natural-language logging; do not attempt `.fit` import.
- No data and the runner has none to import → still write a minimal profile from their answers so other commands work; skip the deck until at least one run is logged.
</Stop_Conditions>
