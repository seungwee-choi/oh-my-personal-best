---
description: "What should I run today?"
---

# pb-today

## Dispatch

Delegate to `oh-my-personal-best:session-coach` to prescribe today's session.

Before prescribing, session-coach must load:
- `.ompb/plan-state.json` — current phase, plan_week, this_week_target_km,
  key_sessions, critic_approved
- `.ompb/training-log.jsonl` — last 7 days of actuals for fatigue check
- `.ompb/runner-profile.json` — experience, injury_history
- `.ompb/goal.json` — event, target_time (for pace zone anchoring)

Pass any additional context from the runner as:

```text
$ARGUMENTS
```

session-coach responds with a fast, direct single-session prescription (type, distance,
structure, pace range, purpose). If `critic_approved` is `false` in plan-state.json,
session-coach will not prescribe — it will inform the runner that the plan is pending
critic review and suggest running `/pb-plan` first.
