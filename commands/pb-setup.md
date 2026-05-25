---
description: "First-run setup — import your data, build your profile, get your first analysis report"
---

# pb-setup

## Dispatch

1. Read and follow the bundled skill instructions: `skills/pb-setup/SKILL.md`.
2. Treat the user's arguments (an optional path to a COROS/Garmin export, `.fit`/`.zip`, or `.csv`) as:

```text
$ARGUMENTS
```

In short: resolve `$CLAUDE_PLUGIN_ROOT` (scripts) and `OMPB_HOME` (data), check `fitdecode`,
import the runner's data, bootstrap `runner-profile.json` (+ `pb-history.json`) from it, optionally
set a goal, then run `race-analyst` + `build_report.py` to deliver the first report — and show the
core loop (`/pb-today`, `/pb-log`, `/pb-report`, `/pb-plan`).

If `skills/pb-setup/SKILL.md` is not readable from the working directory, locate it under the
active `CLAUDE_PLUGIN_ROOT` / package root / installed plugin directory and continue.
