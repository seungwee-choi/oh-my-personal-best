---
description: "Generate a comprehensive, print-ready athlete training report (HTML/PDF)"
---

# pb-report

## Dispatch

1. Read and follow the bundled skill instructions: `skills/pb-report/SKILL.md`.
2. Treat any arguments (`--lang ko`, `--no-diagnosis`) as:

```text
$ARGUMENTS
```

In short: ensure the training log has data, have `race-analyst` write `$OMPB_HOME/diagnosis.json`
(unless `--no-diagnosis`), then run `python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_report.py" [--lang ko]`
to render `$OMPB_HOME/reports/report-<date>.html` (self-contained, print/PDF-ready) and offer to open it.

If `skills/pb-report/SKILL.md` is not readable from the working directory, locate it under the
active `CLAUDE_PLUGIN_ROOT` / package root / installed plugin directory and continue.
