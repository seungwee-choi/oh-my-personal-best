---
description: "Show this week's training plan as a visual, print-ready weekly card"
---

# pb-week

## Dispatch

1. Read and follow the bundled skill instructions: `skills/pb-week/SKILL.md`.
2. Treat any arguments (`--lang ko`) as:

```text
$ARGUMENTS
```

In short: ensure `$OMPB_HOME/plan-week.json` exists (derive it via `session-coach` from the
periodized plan, or route to `/pb-plan` if there's no plan/goal yet), then run
`python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_week.py" [--lang ko]` to render
`$OMPB_HOME/weeks/week-<date>.html` (self-contained, one-page printable) and offer to open it.

If `skills/pb-week/SKILL.md` is not readable from the working directory, locate it under the
active `CLAUDE_PLUGIN_ROOT` / package root / installed plugin directory and continue.
