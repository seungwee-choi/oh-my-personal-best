---
description: "Log/manage an injury — triage, track the episode, stage the return-to-run"
---

# pb-injury

## Dispatch

Invoke the `oh-my-personal-best:pb-injury` skill. It routes to `physio-advisor` (the safety gate +
the single writer of injury state) — triage first (GREEN/YELLOW/RED), then, for a genuine injury,
capture the episode behind a confirm gate, stage the return-to-run ladder, and guardrail the plan.

Any pain/injury signal takes priority over training prescriptions. RED-flag symptoms (chest pain,
dizziness, "something popped", numbness) escalate to "seek medical care now" — not a substitute for
medical evaluation.

Pass the runner's words as:

```text
$ARGUMENTS
```
