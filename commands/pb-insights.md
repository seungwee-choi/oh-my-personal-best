---
description: "Surface training highlights — trends, self-PRs, and hidden signals (와우 모먼트)"
---

# pb-insights

## Dispatch

Invoke the `oh-my-personal-best:pb-insights` skill. It runs the deterministic detector pipeline
(`ompb_core.detect_insights`) over the full log + goal/profile/plan/PB/body and surfaces the
top score-ranked cards — cross-activity trends, self-relative PRs, and hidden signals (incl. a
fatigue/load-spike warning). `race-analyst` can narrate the "so what" against the goal.

Needs ~8+ logged runs for self-relative signals; with fewer, encourage more logging rather than
fabricating a highlight.

Pass any context from the runner as:

```text
$ARGUMENTS
```
