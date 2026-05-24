---
name: pb-deck
description: Render the runner's analysis as a self-contained HTML slide deck
argument-hint: "[--title \"...\"] [--no-diagnosis]"
level: 3
---

<Purpose>
pb-deck turns the runner's training log and analysis into a single self-contained HTML slide
deck — inline SVG charts, no server, no internet — that the runner can open in a browser,
screenshot, or share. It pairs deterministic data visualization (`scripts/build_deck.py`) with
an optional narrative diagnosis from race-analyst, so the deck shows both the numbers and what
they mean.
</Purpose>

<Use_When>
- The runner asks to "see", "visualize", "show me", or "make a report/deck/slides" of their data
- After a bulk import (e.g., a COROS/Garmin .fit import) when the runner wants an overview
- A periodic check-in where a visual summary is more useful than text
- Keyword triggers: "deck", "report", "시각자료", "슬라이드", "보고서", "visualize", "차트"
</Use_When>

<Do_Not_Use_When>
- The training log is empty — route to data import first (`/pb-log` with a .fit/.zip/CSV path)
- The runner wants a single number or quick query — answer via data-logger instead
</Do_Not_Use_When>

<Steps>

## Step 1 — Ensure data exists
Confirm `.ompb/training-log.jsonl` exists and is non-empty. If absent, tell the runner to import
first (`/pb-log <path-to-.fit/.zip/.csv>`) and stop.

## Step 2 — Produce the diagnosis narrative (unless --no-diagnosis)
Delegate to `oh-my-personal-best:race-analyst` to analyze the log (+ `goal.json`,
`runner-profile.json` if present) and write `.ompb/diagnosis.json` with this shape:
```json
{
  "summary": "one-paragraph plain-language overview of the training picture",
  "limiter": "the #1 limiting factor (e.g. threshold endurance, speed, durability)",
  "feasibility": "goal realism verdict + one-line rationale (omit if no goal set)",
  "observations": ["evidence-backed observation", "..."],
  "generated_at": "ISO-8601"
}
```
race-analyst is read-only on state files; have the orchestrator write the JSON from its verdict.
If the runner passed `--no-diagnosis`, skip this step — the deck renders pure data visualization.

## Step 3 — Render the deck
Run:
```
python3 scripts/build_deck.py --tz <local-tz> [--title "<title>"]
```
`build_deck.py` reads the log and auto-discovers `diagnosis.json`, `goal.json`, `pb-history.json`,
and `plan-state.json` in `.ompb/`, then writes `.ompb/decks/deck-<YYYY-MM-DD>.html`. It needs only
the Python standard library. Slides for diagnosis / PBs / next block appear only when their source
files exist; otherwise they are omitted (graceful degradation).

## Step 4 — Deliver
Report the output path and offer to open it (e.g., `open <path>` on macOS). Summarize in one line
what the deck contains (slide count + headline stats).

</Steps>

<Stop_Conditions>
- Log empty → stop, instruct to import first.
- build_deck.py exits non-zero → report stderr; do not claim a deck was produced.
</Stop_Conditions>
