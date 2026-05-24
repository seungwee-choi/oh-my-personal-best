---
description: "Render your training analysis as a self-contained HTML slide deck"
---

# pb-deck

## Dispatch

1. Read and follow the bundled skill instructions: `skills/pb-deck/SKILL.md`.
2. Treat the user's arguments as:

```text
$ARGUMENTS
```

In short: ensure `$OMPB_HOME/training-log.jsonl` has data, optionally have `race-analyst` write
`$OMPB_HOME/diagnosis.json`, then run `python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_deck.py" --tz <local>` to produce
`$OMPB_HOME/decks/deck-<date>.html`, and offer to open it.

If `skills/pb-deck/SKILL.md` is not readable from the working directory, locate it under the
active `CLAUDE_PLUGIN_ROOT` / package root / installed plugin directory and continue.
