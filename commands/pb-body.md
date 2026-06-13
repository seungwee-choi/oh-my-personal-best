---
description: "Log weight and get trend-aware fueling guidance (race weight, under-fueling, safe rate)"
---

# pb-body

## Dispatch

Invoke the `oh-my-personal-best:pb-body` skill. It routes to `fuel-advisor`, which logs the weight
(`body.jsonl`), reads the trend (`ompb_core.body_summary` — current/ma7/ma30/rate, race-weight gap,
under-fueling flag), and grounds fueling advice in the trajectory. Too-fast loss (>~1%/week) or an
under-fueling signal is a stop-and-reassess, never an endorsement of "leaner = faster".

Signs of disordered eating or a clinical dietary condition → refer to a registered dietitian/physician.

Pass the runner's words as:

```text
$ARGUMENTS
```
