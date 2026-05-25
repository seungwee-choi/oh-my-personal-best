---
name: pb-report
description: Generate a comprehensive, print-ready athlete training report (HTML/PDF)
argument-hint: "[--lang ko] [--no-diagnosis]"
level: 3
---

<Purpose>
pb-report produces a comprehensive, print/PDF-ready **athlete training report** — a full
sports-science-style assessment of the runner's training history, fitness, limiter, and
recommendations in one self-contained HTML document. It pairs the runner's data (training log,
profile, PBs) with race-analyst's narrative diagnosis and renders them into a vendored, offline,
print-friendly template (inline SVG charts, no external dependencies).
</Purpose>


<Use_When>
- The runner asks for a "report", "full report", "assessment", "리포트", "분석 리포트", "PDF"
- They want something to print, export to PDF, or send to a coach
</Use_When>

<Do_Not_Use_When>
- The training log is empty — route to `/pb-setup` or `/pb-log` first.
- They want a quick single stat — answer via `data-logger`.
</Do_Not_Use_When>

<Steps>

## Step 1 — Ensure data exists
Confirm `$OMPB_HOME/training-log.jsonl` exists and is non-empty (run `/pb-setup` first if not).

## Step 2 — Diagnosis narrative (unless --no-diagnosis)
If `$OMPB_HOME/diagnosis.json` is missing or stale, delegate to `oh-my-personal-best:race-analyst`
to analyze the log (+ `runner-profile.json`, `goal.json`) and have the orchestrator write
`$OMPB_HOME/diagnosis.json` (`{summary, limiter, observations[], generated_at}`). The report's
Executive Summary, Limiter, and Key Findings sections come from this. Without it the report still
renders (those sections are empty) — prefer to generate it.

## Step 3 — Render the report
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_report.py" [--lang ko]
```
`build_report.py` reads `$OMPB_HOME` state, assembles the `REPORT_DATA` object (athlete, window,
totals, PBs, monthly volume/pace/HR, HR-by-pace efficiency, intensity mix + HR-zone split, recent
weeks, diagnosis), injects it into the vendored template (`templates/report.html` /
`report.ko.html`), and writes `$OMPB_HOME/reports/report-<date>.html`. Standard library only —
fully offline, print/PDF-ready.

## Step 4 — Deliver
Report the path and offer to open it (`open <path>` on macOS) or print to PDF (the template has a
print stylesheet). Summarize headline findings in one line.

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset (not an installed plugin) → run `python3 scripts/build_report.py` from the repo.
- Template missing → the plugin ships `templates/report.html`; reinstall if absent.
</Stop_Conditions>
