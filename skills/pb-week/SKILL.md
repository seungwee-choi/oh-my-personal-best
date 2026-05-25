---
name: pb-week
description: Show this week's training plan as a visual, print-ready weekly card
argument-hint: "[--lang ko]"
level: 3
---

<Purpose>
pb-week renders the runner's CURRENT week of training as a glanceable, motivating, print-ready
card — 7 days at a glance with each session's distance, target pace, structure (warm-up / main /
cool-down) and purpose, plus a weekly load summary and coach notes. It's the forward-looking
"what do I run this week" view, the companion to `/pb-today` (one day) and `/pb-plan` (the whole block).
</Purpose>

<Use_When>
- The runner asks for "this week", "weekly plan", "training schedule", "주간 계획", "이번 주 훈련표", "week card"
- After `/pb-plan` or `weekly-adapt` produces/updates the week
</Use_When>

<Do_Not_Use_When>
- No plan or goal exists yet → route to `/pb-plan` first (a week is derived from the periodized plan).
- The runner wants only today's single session → use `/pb-today` (session-coach).
</Do_Not_Use_When>

<Data_contract>
The week is stored at `$OMPB_HOME/plan-week.json` as the `PLAN_DATA` object the template consumes:
```json
{ "athlete": {"label","experience"}, "today": "YYYY-MM-DD",
  "goal": {"event","target_time","race_date","weeks_to_race"},
  "week": {"plan_week","total_weeks","phase","start_date","end_date","target_km","prev_week_km","ramp_pct","focus"},
  "days": [ {"dow","date","type","title","distance_km","pace","hr_zone","structure","purpose","done"} ...×7 ],
  "coach_notes": ["..."], "critic_approved": true }
```
`type` ∈ easy|long|tempo|interval|recovery|rest|cross. `summary` is auto-computed by build_week.py if absent.
</Data_contract>

<Steps>

## Step 1 — Ensure a week exists
If `$OMPB_HOME/plan-week.json` is missing or stale (wrong week), generate it:
- It comes from the periodized plan. If there's no `plan-state.json`/`goal.json`, route to `/pb-plan` first.
- Otherwise delegate to `oh-my-personal-best:session-coach` to prescribe the 7 days for the current
  `plan-state.json` phase/target (paces derived from `runner-profile.json` PBs), and have the
  orchestrator write `$OMPB_HOME/plan-week.json` in the contract above. Respect the safety gate —
  if `physio-advisor` has an active YELLOW/RED, the week must reflect it.

## Step 2 — Render the card
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/build_week.py" [--lang ko]
```
build_week.py injects `plan-week.json` into the vendored self-contained template
(`templates/week.html` / `week.ko.html`), sets `today`, computes the load summary if missing, and
writes `$OMPB_HOME/weeks/week-<date>.html`. Standard library only — offline, one-page printable.

## Step 3 — Deliver
Report the path, offer to open it (`open <path>`) or print. Summarize the week in one line
(phase, target km, the two key sessions).

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset → run `python3 scripts/build_week.py` from the repo.
- No plan-week.json and no plan to derive it from → tell the runner to run `/pb-plan` first.
</Stop_Conditions>
