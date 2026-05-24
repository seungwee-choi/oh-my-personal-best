---
name: weekly-adapt
description: Weekly training-plan adaptation loop based on logged actuals
argument-hint: "[week check-in notes]"
level: 4
---

<Purpose>
weekly-adapt is the weekly adaptation loop. It runs every week to
compare what was planned against what was actually done, assess fatigue and compliance, and adapt
next week's plan accordingly — advancing, holding, or deloading based on real data. Because it
runs on a weekly cadence, the plan stays alive and responsive rather than static. A plan that
ignores what happened last week is not a plan; it is a wish list.
</Purpose>

<Use_When>
- The runner checks in at the end of or during a training week ("이번 주 계획 조정해줘", "weekly
  check-in", "adjust this week", "how did I do?")
- Keyword triggers detected: "weekly", "이번 주", "adjust", "week check-in", "this week"
- A new week is starting and the runner wants next week calibrated to actual last-week performance
- plan-state.json exists and `critic_approved: true` (an active plan is in progress)
- After recovering from illness or a missed-session cluster and the plan needs resetting
</Use_When>

<Steps>

## Step 1 — Collect and Aggregate Actuals (data-logger)

Invoke `oh-my-personal-best:data-logger` to collect and aggregate this week's training data.

If the runner provided check-in notes in `$ARGUMENTS`, pass them to data-logger for ingestion
first (natural-language path). data-logger normalizes any new entries into `training-log.jsonl`.

data-logger then produces the weekly summary:
- Planned sessions (from plan-state.json `key_sessions`) vs. actual sessions logged
- Compliance rate: sessions completed / sessions planned (%)
- Total actual volume (km) vs. `this_week_target_km`
- Intensity distribution: count by session type (easy / tempo / interval / long / rest / missed)
- Missed sessions: date, type, and whether the runner noted a reason

This summary is the evidence base for all downstream agents. Do not proceed until data-logger
confirms the aggregation is complete.

## Step 2 — Compliance and Fatigue Assessment (race-analyst)

Invoke `oh-my-personal-best:race-analyst` with the weekly summary from Step 1 and the last
6–8 weeks of `training-log.jsonl`.

race-analyst assesses:
- **Compliance trend**: is the runner executing the prescribed plan? A pattern of
  under-execution signals the plan is too ambitious; over-execution signals under-prescription
  or the runner ignoring pacing guidance.
- **Fatigue signals**: RPE trend over the past 7–14 days (rising RPE at the same paces =
  accumulated fatigue); HR drift; performance plateau or regression.
- **Overtraining markers**: volume ramp >10%/week sustained across 2+ weeks; 3+ missed sessions
  in the rolling 14-day window; consecutive hard sessions without recovery.
- **Fitness progression**: are paces improving at stable RPE? Is the runner adapting as expected
  for their current phase?

race-analyst returns one of three load-state verdicts:
- **ADVANCE**: runner is adapting well — progress next week as planned
- **HOLD**: compliance or fatigue signals warrant repeating this week's load level
- **DELOAD**: clear fatigue or overtraining signals — reduce volume 20–30%, no intensity work

## Step 3 — Physio Safety Check (physio-advisor) — PRIORITY OVERRIDE

Invoke `oh-my-personal-best:physio-advisor` with the weekly summary and the last 14–21 days of
`training-log.jsonl`.

physio-advisor checks for:
- Any pain or injury keywords in session notes
- Load ramp violations (>10%/week for 2+ consecutive weeks)
- RPE ≥ 7 on sessions logged as "easy" for 3+ consecutive days
- Missed-session clusters that may indicate the runner is managing pain silently
- Known injury-history sites showing any signal

physio-advisor issues a traffic-light verdict:

**GREEN**: No injury signals detected. Proceed with race-analyst's load-state verdict from Step 2.

**YELLOW**: Modify or reduce. physio-advisor's override directive applies:
  - Its recommended volume reduction and session substitutions take precedence over
    race-analyst's ADVANCE verdict. If race-analyst said ADVANCE but physio-advisor says YELLOW,
    the effective directive is HOLD or partial DELOAD per physio-advisor's specification.
  - The physio directive is passed to plan-architect in Step 4.

**RED**: Suspend training load prescriptions. Do not proceed to plan-architect for progression.
  - Instruct the runner to follow physio-advisor's guidance and seek sports-medicine evaluation.
  - Stop this pipeline iteration. Re-run weekly-adapt only after physio-advisor clears RED status.
  - Do NOT set `critic_approved: true` on any plan revision while RED is active.

> physio-advisor's YELLOW or RED directive OVERRIDES any training progression from any other
> agent. This is non-negotiable. Safety precedes performance.

## Step 4 — Adapt Next Week (plan-architect)

Invoke `oh-my-personal-best:plan-architect` with:
- Current plan-state.json (phase, plan_week, total_weeks, this_week_target_km, key_sessions)
- race-analyst's load-state verdict (ADVANCE / HOLD / DELOAD)
- physio-advisor's directive (GREEN / YELLOW override / RED — only GREEN or YELLOW proceed here)
- The weekly compliance summary from Step 1

plan-architect adjusts next week's plan:

**ADVANCE**: increment `plan_week`, apply the scheduled volume increase (respecting ~10%/week
  cap), progress key sessions per the periodization phase. If a down week is due (every 3–4
  weeks), apply the scheduled ~20–25% volume reduction regardless of the ADVANCE verdict.

**HOLD**: keep `this_week_target_km` at the same level, repeat the same key session types, do
  not increment phase or introduce new intensity. Note the hold reason in plan-state.

**DELOAD** (or YELLOW physio override): reduce volume 20–30%, replace all tempo/interval
  sessions with easy runs, increase rest days. Set a flag in plan-state indicating a recovery
  week is in progress.

plan-architect writes the updated `plan-state.json` with `critic_approved: false`.

**Do not show the adjusted plan to the runner yet.**

## Step 5 — Gate the Adjustment (plan-critic)

Invoke `oh-my-personal-best:plan-critic` with:
- The adapted plan-state.json from Step 4
- runner-profile.json and goal.json for context
- The physio-advisor verdict from Step 3

plan-critic validates the adjustment:
- Weekly ramp from last week's actual volume to next week's target does not exceed ~10%
- If physio-advisor issued YELLOW, the adaptation respects the override directive
- Key session types are appropriate for the current phase
- Rest day structure is sound

**If APPROVED**: orchestrator sets `critic_approved: true` in plan-state.json. Proceed to
delivery.

**If REJECTED**: route back to plan-architect with the specific required fixes. Unlike the
full race-plan pipeline, weekly adjustments should converge in 1–2 rounds. If a second
rejection occurs, default to a conservative HOLD/DELOAD to ensure runner safety and flag the
constraint to the runner.

## Step 6 — Deliver the Weekly Adaptation

After `critic_approved: true` is set, deliver to the runner:

1. **This week's summary**: compliance rate, actual vs. planned volume, key observations from
   race-analyst (one sentence on fitness trend).
2. **Physio status**: GREEN / YELLOW / RED verdict and any active directives (if YELLOW, what
   was modified and why).
3. **Next week's plan**: the adapted `this_week_target_km`, key session types, and any changes
   from the original plan with the reason (e.g., "Holding volume at 55 km — RPE trending up
   at steady paces this week; priority is consolidation not progression").
4. **Prompt**: remind the runner to use `/pb-log` after each session and to check in again
   next week with `weekly-adapt`.

</Steps>

<Stop_Conditions>
- Stop if physio-advisor issues RED — do not adapt the plan; route the runner to physio
  guidance and stop this iteration.
- Stop if plan-state.json does not exist or `critic_approved` has never been set true —
  the runner needs a base plan first; route to `race-plan` skill.
- Stop if `goal.json.weeks_remaining` reaches 0 or the race date has passed — the plan cycle
  is complete; offer a post-race debrief via race-analyst instead.
- Do not stop between Steps 1–5 for runner confirmation — deliver the adapted plan as a
  complete weekly brief, not as intermediate agent outputs.
</Stop_Conditions>
