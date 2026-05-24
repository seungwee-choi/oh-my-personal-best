---
name: race-week
description: Parallel race-week consult producing a race-day brief
argument-hint: "[race details]"
level: 3
---

<Purpose>
race-week is the parallel race-week consult. When the runner's race is within
7 days, three specialists consult in parallel — pace-strategist, fuel-advisor, and
physio-advisor — and their outputs are synthesized into a single, self-contained race-day brief
the runner can print, screenshot, or read on race morning. No multi-tab research required; one
brief covers everything.
</Purpose>

<Use_When>
- The race is within 7 days ("다음 주가 대회야", "race is next week", "race week", "대회 D-7",
  "taper", "race on Sunday")
- Keyword triggers detected: "race week", "대회 D-7", "taper", "race day", "race is [day]"
- The runner explicitly requests a race-day brief or pre-race guidance
- goal.json `race_date` is within 7 days of today
</Use_When>

<Steps>

## Step 1 — Load Context

Before firing the parallel consult, load:
- `.ompb/goal.json` — event, target_time, race_date, weeks_remaining
- `.ompb/runner-profile.json` — current_pb, weight_kg, experience, injury_history
- `.ompb/plan-state.json` — current phase (should be taper), plan_week,
  this_week_target_km, critic_approved
- Recent `.ompb/training-log.jsonl` — last 21 days to assess taper compliance and
  detect any late-appearing pain signals

Pass `$ARGUMENTS` (if provided) as additional race context — course profile, expected weather,
start time, aid-station spacing — to all three parallel agents.

> Safety gate: if the training log shows any unresolved RED verdict from physio-advisor, or any
> pain signal in the last 7 days, route to physio-advisor synchronously before firing the
> parallel consult. Do not produce a race-day brief while a RED verdict is active.

## Step 2 — Parallel Consult (pace-strategist + fuel-advisor + physio-advisor)

Fire all three agents simultaneously. Do not wait for one before starting the others.

### pace-strategist (`oh-my-personal-best:pace-strategist`)
Produces the racing strategy brief:
- Goal assessment: target time vs. fitness-predicted time, feasibility rating
- Target goal pace (MM:SS/km) and plan-B pace
- Per-km or per-5-km split table with cumulative times
- Course and weather adjustments (if race details provided in $ARGUMENTS)
- Segment effort cues per race third (conversational / controlled / working / race mode)
- Pacing rules (3–5 numbered, e.g., "The first km will feel too easy — that is the plan")
- Plan-B: trigger condition (off goal pace at midpoint check), fallback time and pace
- Fueling checkpoint km markers (timing only — fuel-advisor provides amounts)

### fuel-advisor (`oh-my-personal-best:fuel-advisor`)
Produces the nutrition brief:
- Carb-loading protocol (triggered automatically since race is within 3 days or fewer):
  - Full marathon: 3-day protocol (Day 3 / Day 2 / Day 1 before race)
  - Half marathon: 1-day protocol
  - 10K: no formal carb-loading; normal intake guidance
- Pre-race meal: timing (3–4 h before gun), composition, "tested in training" requirement
- In-race gel/fluid timed schedule: amounts, km markers aligned with pace-strategist's split
  table, aid-station coordination
- Caffeine plan: dose (mg/kg), timing, "tested in training" requirement
- Post-race recovery nutrition: within 30 min of finish

### physio-advisor (`oh-my-personal-best:physio-advisor`)
Produces the taper and final-week check:
- Taper compliance review: is the runner honoring reduced volume and intensity?
- Taper week training guidance: what to run (short, easy, race-pace strides only), what to
  avoid (no new training stresses, no racing-intensity sessions)
- Sleep and recovery checklist: target 7–9 h/night in the final week; avoid alcohol; feet
  elevation; avoid standing for extended periods the day before
- Final-week niggle check: assessment of any discomfort reported in recent training-log notes;
  traffic-light triage (GREEN / YELLOW / RED) with explicit action directive
- Strength/mobility: last-opportunity prehab relevant to the runner's injury history (light,
  do not introduce new stresses)
- Logistics reminders: race kit check (shoes used in training, not new), nutrition practiced
  in training, warm-up plan

## Step 3 — Synthesize into One Race-Day Brief

After all three parallel agents complete, synthesize their outputs into a single, unified
race-day brief with these sections in order:

---
**RACE-DAY BRIEF — [event] [target_time] — [race_date]**

### 1. Pacing Plan
- Goal pace and plan-B pace
- Full split table (per-km for 10K/half; per-5-km for full) with cumulative times,
  effort cues, and fueling checkpoints marked inline
- Pacing rules (numbered, concrete)
- Plan-B trigger and fallback

### 2. Fueling Schedule
- Timed table: time from gun, km marker, action (gel/fluid/electrolyte + amount)
- Pre-race meal timing and composition
- Caffeine plan
- Carb-loading protocol (if race ≤ 3 days away, include the day-by-day protocol)

### 3. Taper & Recovery Checklist
- What to run this week (sessions, distances, intensities)
- Sleep, hydration, feet-up logistics
- Race kit checklist
- Final-week niggle status (physio-advisor GREEN / YELLOW / RED verdict)
- Any prehab exercises for the final week

### 4. Plan-B
- Trigger: "If I am [X] s/km off goal pace at km [midpoint]..."
- Action: switch to plan-B pace [MM:SS/km], revised finish time [H:MM:SS]
- Framing: "A strong finish at fitness-predicted pace beats a blown-up race"

---

Resolve any conflicts between agents (e.g., pace-strategist places a gel at km 16 but
fuel-advisor schedules it at km 17) in favor of the more conservative or physiologically
safer option, and note the resolution.

Flag any physio YELLOW or RED finding prominently at the top of the brief with the override
directive. A RED finding stops the brief — the runner needs medical clearance, not a race plan.

</Steps>
