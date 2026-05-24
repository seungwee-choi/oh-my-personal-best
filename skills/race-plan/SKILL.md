---
name: race-plan
description: Goal to complete periodized marathon training plan in one shot
argument-hint: "<goal, e.g. 'sub-3:30 full in 16 weeks'>"
level: 4
---

<Purpose>
race-plan is the one-shot plan builder. It takes a single runner goal
statement and produces a fully periodized training plan — Base → Build → Peak → Taper — in one
end-to-end pipeline, gated by plan-critic before the runner ever sees a session. It handles new
runners (no profile yet) through experienced runners with full history. The runner provides a
goal; the pipeline does the rest.
</Purpose>

<Use_When>
- The runner states a target event and finish time ("sub-3:30 full marathon in 16 weeks",
  "풀코스 sub-3:30 만들고 싶어", "I want to run a sub-4 marathon")
- The runner uses a keyword trigger: "race plan", "훈련 계획", "sub-N", or any goal time expression
- A new training cycle is starting from scratch and needs full periodization
- The existing plan has been discarded or is outdated and a fresh plan is needed
</Use_When>

<Do_Not_Use_When>
- Only a single day's session is needed — use `/pb-today` (session-coach) instead
- A plan already exists and only the current week needs adjustment — use `weekly-adapt` instead
- The race is within 7 days — use `race-week` for the final race-day brief instead
- The runner reports pain or injury before a plan exists — route to physio-advisor first; do not
  build a plan until physio-advisor issues GREEN or YELLOW clearance
</Do_Not_Use_When>

<Steps>

## Step 1 — Ensure Runner State Exists

Load `$OMPB_HOME/runner-profile.json` and `$OMPB_HOME/goal.json`.

If either file is missing or goal.json has no `target_time` / `race_date`, collect the minimum
required fields from the runner before proceeding. Use data-logger (`oh-my-personal-best:data-logger`)
to create or update these files. The minimum required:

- **Current fitness anchor**: most recent race result (distance + time + date), or recent time
  trial, or current PB at any distance. "I've never raced" → ask for a recent long run pace.
- **Weekly mileage**: current average km/week (or miles/week — convert).
- **Target event + time**: full / half / 10K and the goal finish time.
- **Race date**: the specific date or "in N weeks from today".

Do not block on optional fields (weight, injury history, name). Collect them if offered; proceed
without them if not. Invoke data-logger to write `runner-profile.json` and `goal.json` from
the collected answers.

> Safety gate: if the runner mentions any pain, injury, or physical symptom while answering these
> questions, route immediately to physio-advisor before continuing this pipeline.

## Step 2 — Fitness Diagnosis (race-analyst)

Invoke `oh-my-personal-best:race-analyst` with the runner's state files as context.

race-analyst must produce:
- Current fitness estimate (predicted equivalent time at goal distance)
- Inferred training paces (easy / marathon / threshold / interval)
- Goal feasibility verdict: REALISTIC / AGGRESSIVE / UNREALISTIC
- The #1 limiting factor (aerobic endurance / lactate threshold / VO2max speed /
  running economy / durability)
- Log observations and any red flags

Do not proceed to Step 3 until race-analyst's diagnosis is complete. If race-analyst returns
UNREALISTIC, surface this finding to the runner with the quantified rationale before continuing —
offer to build toward a more realistic intermediate goal or proceed knowing the challenge.

## Step 3 — Periodized Plan Design (plan-architect)

Invoke `oh-my-personal-best:plan-architect` with:
- goal.json (event, target_time, race_date, weeks_remaining)
- runner-profile.json (weekly_mileage_km, experience, current_pb, injury_history)
- race-analyst's full diagnosis from Step 2

plan-architect must produce:
- Full phase-by-phase periodization: Base → Build → Peak → Taper, with week ranges derived from
  `goal.json.weeks_remaining` (not hardcoded defaults)
- Volume progression respecting ~10%/week cap with down weeks every 3–4 weeks
- Taper: 2–3 weeks (full marathon), 1–2 weeks (half), 1–2 weeks (10K) — mandatory, never compressed
- Key session types per phase (not full session prescriptions — those are session-coach's domain)
- Target pace zones derived from race-analyst's fitness estimate

plan-architect writes `$OMPB_HOME/plan-state.json` with `critic_approved: false`.

**Never show this plan to the runner yet.**

## Step 4 — First Week Session Fill (session-coach)

Invoke `oh-my-personal-best:session-coach` to populate the concrete sessions for Week 1 only,
based on plan-state.json and the runner's current load.

session-coach provides the full 7-day structure: types, distances, structures, pace ranges,
rest day placement, and purpose statements.

This output is held pending plan-critic approval in Step 5. Do not deliver it to the runner yet.

## Step 5 — Safety and Quality Gate (plan-critic) — MANDATORY

Invoke `oh-my-personal-best:plan-critic` with:
- The full periodization plan from Step 3
- The Week 1 sessions from Step 4
- runner-profile.json (injury_history, current_pb, experience)
- goal.json (target_time, weeks_remaining)
- plan-state.json

plan-critic evaluates the complete plan against its physiological checklist:
weekly ramp rate, taper adequacy, intensity distribution, long-run progression, goal time
realism, injury history respect, rest days, and phase coherence.

### Gate logic (max 3 revision rounds):

**If APPROVED:**
- The orchestrator sets `critic_approved: true` in `$OMPB_HOME/plan-state.json`
- The orchestrator also snapshots the approved plan to `$OMPB_HOME/plans/plan-<YYYY-MM-DD>.json`
  (today's date, never overwritten) to retain full plan history.
- Proceed to Step 6

**If REJECTED (round 1 or 2):**
- Do NOT set `critic_approved: true`
- Pass plan-critic's required fixes back to plan-architect (Step 3) with the specific CRITICAL
  and MAJOR findings
- plan-architect revises the plan addressing every required fix
- Re-submit to plan-critic (return to top of Step 5)
- Track the round number

**If REJECTED after round 3:**
- Do NOT set `critic_approved: true`
- Surface the unresolved issues to the runner with a plain-language explanation
- Offer to adjust the goal or seek a professional running coach for the specific constraint
- Stop the pipeline

> Safety override: if physio-advisor has issued an unresolved RED verdict at any point,
> plan-critic will not approve. Do not attempt further revisions — resolve the RED verdict first.

## Step 6 — Deliver the Approved Plan

Only after `critic_approved: true` is set in `plan-state.json`, deliver the full plan to the
runner:

1. **Fitness snapshot**: current fitness estimate, goal feasibility verdict, and the #1 limiter
   to address (from race-analyst).
2. **Periodization overview**: phase table with week ranges, volume targets, and key session types.
3. **Week 1 sessions**: the full 7-day concrete schedule with structures, paces, and purpose.
4. **Key rules**: the 3–5 most important principles for this specific runner's plan (e.g.,
   "Your #1 limiter is aerobic base — resist the urge to add extra tempo sessions in base phase").
5. **Next step prompt**: remind the runner they can use `/pb-today` for daily session details,
   `/pb-log` to record completed sessions, and the `weekly-adapt` skill each week to keep the
   plan current.

</Steps>

<Stop_Conditions>
- Stop and wait for runner input if the minimum profile data cannot be inferred from context
  (no race history, no recent runs, no weekly mileage — the plan has no anchor).
- Stop and route to physio-advisor if any pain/injury signal appears at any step.
- Stop after 3 plan-critic rejection rounds and surface the unresolved constraints to the runner.
- Stop if `goal.json.weeks_remaining` < 6 — a full periodized plan is not feasible; shift to
  race-execution mode and flag this clearly.
- Do not stop between Steps 2–5 for runner confirmation — the pipeline runs to Step 6 before
  delivering anything. The runner should see an approved plan, not intermediate drafts.
</Stop_Conditions>
