---
description: "Connect your Strava account (one-time) and sync activities automatically"
---

# pb-connect-strava

## Dispatch

1. Read and follow the bundled skill instructions: `skills/pb-connect-strava/SKILL.md`.
2. Treat any arguments (optional `--client-id` / `--client-secret`) as:

```text
$ARGUMENTS
```

In short: guide the runner to create a personal Strava app at https://www.strava.com/settings/api
(Authorization Callback Domain MUST be `localhost`), then run
`python3 "$CLAUDE_PLUGIN_ROOT/scripts/strava_connect.py" --client-id <ID> --client-secret <SECRET>`
(browser → Authorize → automatic localhost capture → writes `$OMPB_HOME/strava.json`), then
`python3 "$CLAUDE_PLUGIN_ROOT/scripts/import_strava.py"` for the first sync. Re-syncs need no
re-auth (refresh token auto-refreshes).

If `skills/pb-connect-strava/SKILL.md` is not readable from the working directory, locate it under
the active `CLAUDE_PLUGIN_ROOT` / package root / installed plugin directory and continue.
