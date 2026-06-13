---
name: pb-injury
description: Log and manage an injury — track the episode, stage the return-to-run, and guardrail the plan
level: 3
---

<Purpose>
pb-injury turns a pain/injury report into a TRACKED episode with a deterministic return-to-run
ladder, instead of advice that evaporates after one chat turn. It is the safety-first entry point:
any pain signal routes here (to `physio-advisor`) BEFORE any training prescription. The episode's
phase caps weekly load and restricts workout types — a guardrail every plan the coach builds must
respect until physio-advisor advances or clears it.
</Purpose>

<Use_When>
- The runner reports pain/injury: "무릎이 아파", "achilles is sore", "16km 뛰고 종아리 땡겨"
- A recovery check-in: "오늘 5km 뛰었는데 통증 없었어", "어제보다 나아졌어"
- "복귀 어떻게 해?", "다시 뛰어도 돼?", "내 부상 상태"
</Use_When>

<Do_Not_Use_When>
- A RED-flag symptom (chest pain, dizziness, "something popped", numbness) → physio-advisor escalates
  to "seek medical care now"; this is not a substitute for medical evaluation.
</Do_Not_Use_When>

<Routing>
Delegate to `oh-my-personal-best:physio-advisor`. It owns injury state (the single writer of
`injuries.jsonl`, via `ompb_core.injury_*`) behind a confirm gate.
</Routing>

<Steps>

## Step 1 — Triage first (safety gate)
physio-advisor issues a GREEN/YELLOW/RED verdict. RED → stop, seek care; no episode/plan changes
until cleared. Transient DOMS (GREEN) → no episode; reassure and continue.

## Step 2 — Capture the episode (propose → confirm)
For a genuine injury, parse the report:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/injury.py" parse "<the runner's words>"
```
Read the proposal back to the runner to CONFIRM (part / side / severity / onset). Only on confirm:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/injury.py" create --part <knee|achilles|…> [--side left|right|both] [--severity N] [--onset YYYY-MM-DD]
```
The starting return-to-run phase is chosen conservatively from severity.

## Step 3 — Stage the return (the ladder)
Explain the phase (rest → walk → walk_run → easy_only → build → full), what it permits, and the rule
to advance (two consecutive pain-free, pain ≤ 2 *running* check-ins) or step back (a flare, pain ≥ 6).
Record check-ins so the deterministic ladder — not motivation — decides progress:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/injury.py" checkin --id <inj-id> [--ran] [--pain-during N] [--pain-after N]
```

## Step 4 — Guardrail the plan
While the episode is open, `ompb_core.injury_snapshot(home)` caps weekly load (`load_cap_pct`) and
restricts `allowed_types`. plan-architect/session-coach build inside that cap; a missed planned
session during the injury reads as recovery (`skipped_injury`), never a penalised lapse.

## Step 5 — Resolve
When pain-free across the ladder:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/injury.py" resolve --id <inj-id>
```
For a RED-flag injury, recommend professional sign-off before resolving.

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset → run `python3 scripts/injury.py …` from the repo.
- RED-flag symptom → escalate to medical care; do not proceed with episode management.
- Ambiguous report (no clear body part / pain cue) → ask one clarifying question; never auto-create.
</Stop_Conditions>
