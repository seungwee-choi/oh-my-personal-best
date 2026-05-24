---
description: "Log a run (.fit/.zip device export, CSV file, or plain language)"
---

# pb-log

## Dispatch

Delegate to `oh-my-personal-best:data-logger` to ingest the following input:

```text
$ARGUMENTS
```

### Input routing

**If `$ARGUMENTS` is a `.fit` file, a `.zip`, or a directory** (e.g., a COROS / Garmin export folder):
- data-logger calls `python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_fit.py" "<path>" --tz <local>`
- `import_fit.py` reads each activity's session summary, types running as easy/long and other
  sports as `cross`, and emits normalized JSONL with `source: "fit"` and `source_id`
- The script appends validated, deduped lines directly to `$OMPB_HOME/training-log.jsonl`;
  re-imports are idempotent (no duplicate `source_id`s)
- Requires the `fitdecode` package (see requirements.txt)

**If `$ARGUMENTS` is a `.csv` file path**:
- data-logger calls `python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_csv.py" "<file.csv>"`
- The script validates, dedupes, and appends normalized lines directly to
  `$OMPB_HOME/training-log.jsonl` with `source: "csv"`

**If `$ARGUMENTS` is a natural-language report** (e.g., "ran 10K in 50:00", "오늘 12km
easy 5:45 뛰었어", "long run 32km done, HR avg 148"):
- data-logger parses the report directly: extract date, type, distance_km, pace, HR, RPE,
  and any notes
- Appends the normalized entry to `$OMPB_HOME/training-log.jsonl` with `source: "nl"`

**In both cases**, data-logger:
- Detects new PBs in any race entries and updates `runner-profile.json` current_pb and
  `$OMPB_HOME/pb-history.json` if faster than current best
- Confirms in one line: `Logged: YYYY-MM-DD · [type] · [distance_km]km · [pace]/km`
  (or `Imported N sessions from [filename]. [K new PBs detected.]` for CSV)
- Does not comment on training quality — analysis is race-analyst's domain
