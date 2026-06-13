---
name: pb-insights
description: Surface "와우 모먼트" — cross-activity trends, self-relative PRs, and hidden signals from the log
level: 3
---

<Purpose>
pb-insights surfaces what Strava/Garmin/Coros don't: CROSS-activity trends, self-relative records,
and hidden patterns with an explanation — "same heart rate, 12s/km faster than two months ago",
"6-week streak of 3+ runs", "longest run ever", "this week's load is +40% (ease off)". It runs a
deterministic detector pipeline over the full log + goal/profile/plan/PB/body and returns
score-ranked cards; the coach narrates the top few. Motivation grounded in the runner's own data.
</Purpose>

<Use_When>
- "내 하이라이트", "뭐 좋아졌어?", "요즘 어때?", "show my progress", "any wins lately?"
- After a sync/import, to celebrate genuine improvements and flag a hidden fatigue spike
- As a section of `/pb-report` (the comprehensive report embeds the top insights)
</Use_When>

<Do_Not_Use_When>
- Fewer than ~8 logged runs → not enough history for self-relative signals; route to `/pb-setup`
  or encourage logging more first (detect returns `[]`).
</Do_Not_Use_When>

<Routing>
Mostly deterministic — `ompb_core.detect_insights(home)`. `race-analyst` can narrate/contextualize
the top cards against the goal when the runner wants the "so what".
</Routing>

<Steps>

## Step 1 — Detect
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/insights.py"        # ompb_core.detect_insights(home, deep=True)
```
Returns score-ranked cards: `{id, kind (improvement|pr|warning|consistency|adaptation), icon,
headline, wow (one-line meaning), stat, score, coach_hint}`. `deep=True` lets zone/decoupling/lap
detectors pull signals from a few recent Strava runs (`analyze_activity`, ≤4 calls — bounded, never
bulk); `deep=False` for a fully offline pass.

## Step 2 — Narrate the top few
Show the highest-scoring 3–5 cards. Lead with the headline number, then the one-line meaning. A
`warning` card (e.g. an acute:chronic load spike) is surfaced honestly — celebrate the wins AND
name the fatigue risk. Use the `coach_hint` as a seed for one sentence of "what to do with it".

## Step 3 — (Optional) deepen
If the runner wants the "so what" for the goal, hand the top cards to `race-analyst` for one
grounded paragraph tying the trend to the limiter and the target race.

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset → run `python3 scripts/insights.py` from the repo.
- `detect` returns `[]` (too few runs / no qualifying signals) → don't fabricate a highlight; tell
  the runner more logged runs will unlock trend insights.
- Never expose detector/data limits as a coaching deficiency (per `dont-expose-analysis-limits`).
</Stop_Conditions>
