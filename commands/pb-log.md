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
- data-logger calls `scripts/import_fit.py "<path>" --dedup-against .ompb/training-log.jsonl --tz <local>`
- `import_fit.py` reads each activity's session summary, types running as easy/long and other
  sports as `cross`, and emits normalized JSONL with `source: "fit"` and `source_id`
- data-logger appends the emitted lines to `.ompb/training-log.jsonl`; the `--dedup-against`
  flag makes re-imports idempotent (no duplicate `source_id`s)
- Requires the `fitdecode` package (see requirements.txt)

**If `$ARGUMENTS` is a `.csv` file path**:
- data-logger calls `scripts/import_csv.py` with the file path as the argument
- `scripts/import_csv.py` emits normalized training-log JSONL lines to stdout
- data-logger validates each line against the training-log.jsonl schema and appends to
  `.ompb/training-log.jsonl` with `source: "csv"`

**If `$ARGUMENTS` is a natural-language report** (e.g., "ran 10K in 50:00", "오늘 12km
easy 5:45 뛰었어", "long run 32km done, HR avg 148"):
- data-logger parses the report directly: extract date, type, distance_km, pace, HR, RPE,
  and any notes
- Appends the normalized entry to `.ompb/training-log.jsonl` with `source: "nl"`

**In both cases**, data-logger:
- Detects new PBs in any race entries and updates `runner-profile.json` current_pb and
  `pb-history.json` if faster than current best
- Confirms in one line: `Logged: YYYY-MM-DD · [type] · [distance_km]km · [pace]/km`
  (or `Imported N sessions from [filename]. [K new PBs detected.]` for CSV)
- Does not comment on training quality — analysis is race-analyst's domain
