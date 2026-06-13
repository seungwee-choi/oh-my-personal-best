---
name: pb-body
description: Log weight and get trend-aware fueling guidance — race weight, under-fueling, safe rate
level: 3
---

<Purpose>
pb-body tracks the runner's weight as a TREND (not a single number) and connects it to fueling, so
"lighter = faster" never overrides health. It logs to `body.jsonl`, computes 7/30-day moving
averages and the kg/week rate, compares to a race-weight target, and flags too-fast loss or
under-fueling — which `fuel-advisor` treats as a stop-and-reassess, not a goal.
</Purpose>

<Use_When>
- "오늘 체중 62.5", "weighed in at 62.5kg", weight check-ins
- "레이스 체중 목표 60", "race weight", fueling for weight management
- "요즘 살 빠지는데 괜찮아?", "왜 페이스가 안 나오지" (possible under-fueling)
</Use_When>

<Do_Not_Use_When>
- Signs of disordered eating, a clinical dietary condition, or rapid unexplained loss → fuel-advisor
  states the coaching boundary and refers to a registered dietitian / physician. Not a weight-loss app.
</Do_Not_Use_When>

<Routing>
Delegate to `oh-my-personal-best:fuel-advisor`, which reads `ompb_core.body_summary(home)` (trend +
race-weight gap + under-fueling signal) and grounds nutrition advice in the trajectory.
</Routing>

<Steps>

## Step 1 — Log (if a weight was reported)
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/body.py" log --kg <float> [--bodyfat <float>] [--note "..."]
```
A race-weight goal: `body.py set-target --kg <float>` (merged into goal.json, never clobbering the race goal).

## Step 2 — Read the trend
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/body.py" summary
```
Gives current weight, ma7/ma30, kg/week rate, race-weight gap, and the under-fueling flag.

## Step 3 — Advise (fuel-advisor)
- If the loss rate exceeds ~1%/week of bodyweight, or the under-fueling flag is set → LEAD with that:
  reassess intake and recovery before any leanness framing. Too-fast loss costs muscle, immunity, and
  performance.
- Otherwise, ground daily/long-run/race fueling in the actual trend and the race-weight gap.

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset → run `python3 scripts/body.py …` from the repo.
- Too few logs for a trend → log the entry and report only the current value; don't infer a rate from one point.
</Stop_Conditions>
