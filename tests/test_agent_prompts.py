"""Prompt lint for `agents/*.md` + `CLAUDE.md` — the "리듬 모드" byte-identical contract.

Run: python3 tests/test_agent_prompts.py  (stdlib only; no pytest required).

Two things are locked here:

1. **Elite is untouched.** Every specialist still carries the headings and load-bearing
   sentences it had before the rhythm work. The rhythm text lives entirely BELOW the
   closing `</Agent_Prompt>` tag, in a section that opens by telling the reader to ignore
   it unless `coach-mode.json` says `rhythm`. A runner with no `coach-mode.json` therefore
   reads exactly today's instructions.
2. **The rhythm sections agree with each other.** The 리듬런 structure and the banned
   vocabulary are one string / one list across files — if a future edit drifts one copy,
   the coach starts prescribing two different workouts under one name.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS = os.path.join(ROOT, "agents")

#: The first sentence of every rhythm section. Exact — the whole byte-identical guarantee
#: for the chat path rests on this line being present and unambiguous.
IGNORE_SENTENCE = (
    "Read `coach-mode.json` in OMPB_HOME. If it is absent or `mode` is not `rhythm`, "
    "IGNORE this section entirely."
)

RHYTHM_HEADING = "## Coaching mode: rhythm"

#: Specialists that got a rhythm section (`design/18` §9 P2 item 17).
RHYTHM_AGENTS = (
    "plan-architect", "plan-critic", "session-coach", "race-analyst",
    "pace-strategist", "fuel-advisor",
)

#: Specialists that must NOT branch on mode. Safety sits ABOVE the mode (`design/18` §10-3),
#: and the logger normalizes data that has no mode.
MODE_FREE_AGENTS = ("physio-advisor", "data-logger")

#: The ONE 리듬런 structure. Same string everywhere it appears.
RHYTHM_RUN_STRUCTURE = "편하게 10분 → (1분 조금 빠르게 + 2분 편하게) × 6 → 편하게 5분"

#: Load-bearing pre-existing text per agent. If a rhythm edit ever rewrites the elite
#: instructions instead of appending to them, one of these disappears.
ELITE_ANCHORS = {
    "plan-architect": [
        "You are Plan Architect.",
        "<Success_Criteria>",
        "2. **Allocate phases.**",
        "- Full marathon advanced: up to 80–100 km/week peak; intermediate: 60–80; beginner: 50–65.",
        "Closing line (mandatory): \"Awaiting plan-critic sign-off. Not shown to runner.\"",
    ],
    "plan-critic": [
        "You are PlanCritic",
        "### 3a. Weekly Volume Ramp Rate",
        "### 3b. Taper Adequacy",
        "### 3c. Intensity Distribution",
        "### 3d. Long-Run Progression",
        "### 3e. Goal Time Realism",
        "**VERDICT: [APPROVED / REJECTED]**",
    ],
    "session-coach": [
        "You are Session Coach.",
        "- Polarize intensity: at least 70–80% of weekly volume should be easy/recovery",
        "**Injury guardrail (hard constraint).**",
        "3. **Select session type.**",
    ],
    "race-analyst": [
        "You are Race Analyst",
        "6. Identify the #1 limiter.",
        "Riegel formula reference: `T2 = T1 × (D2 / D1)^1.06`.",
        "RACE ANALYST DIAGNOSIS",
    ],
    "pace-strategist": [
        "You are Pace Strategist.",
        "**Split Table**",
        "**Plan-B**",
    ],
    "fuel-advisor": [
        "You are FuelAdvisor",
        "**FUELING MODE: [DAILY / LONG-RUN / RACE-DAY]**",
        "nothing new on race day",
    ],
    "physio-advisor": ["<Agent_Prompt>"],
    "data-logger": ["<Agent_Prompt>"],
}


def _read(name):
    with io.open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as fh:
        return fh.read()


def _rhythm_part(text):
    """Everything from the rhythm heading on. Empty string when there is none."""
    idx = text.find(RHYTHM_HEADING)
    return "" if idx < 0 else text[idx:]


def _flat(text):
    """Whitespace-collapsed, so an assertion is not hostage to where a line wraps."""
    return " ".join(text.split())


def _elite_part(text):
    idx = text.find(RHYTHM_HEADING)
    return text if idx < 0 else text[:idx]


# ── 1. elite text survives ────────────────────────────────────────────────────

def test_every_agent_keeps_its_original_headings():
    for name, anchors in ELITE_ANCHORS.items():
        text = _read(name)
        for anchor in anchors:
            assert anchor in text, f"{name}.md lost pre-existing text: {anchor!r}"


def test_agent_prompt_container_is_intact():
    for name in list(RHYTHM_AGENTS) + list(MODE_FREE_AGENTS):
        text = _read(name)
        assert text.count("<Agent_Prompt>") == 1, name
        assert text.count("</Agent_Prompt>") == 1, name
        assert text.index("<Agent_Prompt>") < text.index("</Agent_Prompt>"), name


def test_rhythm_section_lives_below_the_closing_tag():
    """The elite instructions end where they always ended; rhythm is appended after."""
    for name in RHYTHM_AGENTS:
        text = _read(name)
        assert text.index("</Agent_Prompt>") < text.index(RHYTHM_HEADING), (
            f"{name}.md: rhythm text was spliced INSIDE the elite prompt")


def test_frontmatter_unchanged_shape():
    for name in list(RHYTHM_AGENTS) + list(MODE_FREE_AGENTS):
        text = _read(name)
        assert text.startswith("---\n"), name
        head = text.split("---", 2)[1]
        assert re.search(r"^name: %s$" % re.escape(name), head, re.M), name
        assert re.search(r"^model: (opus|sonnet|haiku)$", head, re.M), name


# ── 2. rhythm sections are present, guarded, and consistent ───────────────────

def test_each_rhythm_section_opens_with_the_ignore_sentence():
    for name in RHYTHM_AGENTS:
        text = _read(name)
        part = _rhythm_part(text)
        assert part, f"{name}.md has no rhythm section"
        assert text.count(RHYTHM_HEADING) == 1, f"{name}.md has {text.count(RHYTHM_HEADING)} rhythm headings"
        assert text.count(IGNORE_SENTENCE) == 1, f"{name}.md ignore-sentence count"
        body = part[len(RHYTHM_HEADING):].lstrip("\n")
        assert body.startswith(IGNORE_SENTENCE), (
            f"{name}.md: rhythm section must OPEN with the ignore sentence, got: {body[:120]!r}")


def test_safety_and_logging_agents_have_no_mode_branch():
    for name in MODE_FREE_AGENTS:
        text = _read(name)
        assert RHYTHM_HEADING not in text, f"{name}.md must not branch on coaching mode"
        assert "coach-mode.json" not in text, name


def test_rhythm_run_has_exactly_one_structure_everywhere():
    seen = 0
    for name in RHYTHM_AGENTS:
        part = _rhythm_part(_read(name))
        if "리듬런" in part and ("structure" in part or "구조" in part):
            if RHYTHM_RUN_STRUCTURE in part:
                seen += 1
    assert seen >= 3, (
        "the 리듬런 structure must be spelled out identically in plan-architect, "
        f"plan-critic and session-coach (found {seen})")
    for name in ("plan-architect", "plan-critic", "session-coach"):
        assert RHYTHM_RUN_STRUCTURE in _rhythm_part(_read(name)), name


def test_session_coach_lists_the_banned_vocabulary_and_replacements():
    part = _rhythm_part(_read("session-coach"))
    for word in ("VDOT", "ACWR", "EF", "젖산역치", "VO2max", "Z2", "Z5",
                 "폴라라이즈드", "디커플링", "테이퍼", "베이스/빌드/피크"):
        assert word in part, f"session-coach rhythm section is missing banned word {word}"
    for repl in ("편한 달리기", "리듬런", "긴 달리기", "쉬는 날"):
        assert repl in part, f"session-coach rhythm section is missing replacement {repl}"


def test_plan_architect_rhythm_caps():
    part = _rhythm_part(_read("plan-architect"))
    assert "recreational" in part
    for token in ("20–30 km/week", "16 km", "12–18", "8–12", "2–4"):
        assert token in part, f"plan-architect rhythm caps missing {token!r}"
    assert "40% of this week's total" in part
    assert "catch-up week" in part


def test_plan_critic_accepts_finish_and_habit_goals():
    part = _rhythm_part(_read("plan-critic"))
    assert '`kind: "finish"`' in part
    assert '`kind: "habit"`' in part
    flat = _flat(part)
    assert "Do NOT reject for a missing target time." in flat
    assert "Do NOT reject for a missing race or race date." in flat
    for header in ("Replaces 3a", "Replaces 3b", "Replaces 3c", "Replaces 3d", "Replaces 3e"):
        assert header in part, f"plan-critic rhythm section missing {header}"


def test_race_analyst_reports_three_pillars_not_a_limiter():
    part = _rhythm_part(_read("race-analyst"))
    for pillar in ("꾸준함", "긴 달리기", "리듬"):
        assert pillar in part, pillar
    assert "Do NOT name a single limiter" in part
    assert "exactly one** next step" in part or "exactly one" in part


def test_race_pack_agents_carry_the_two_hour_rules():
    pace = _rhythm_part(_read("pace-strategist"))
    assert "10–15 s/km SLOWER" in pace
    assert "First 3 km" in pace
    fuel = _rhythm_part(_read("fuel-advisor"))
    assert "45분과 90분" in fuel
    assert "매 급수대" in fuel
    assert "새로운 건 아무것도 하지 않는다" in fuel


# ── 3. CLAUDE.md ──────────────────────────────────────────────────────────────

def _claude_md():
    with io.open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8") as fh:
        return fh.read()


def test_claude_md_documents_coach_mode_state():
    text = _claude_md()
    assert "`$OMPB_HOME/coach-mode.json`" in text
    assert '`{"mode": "elite"|"rhythm"}`' in text
    assert "Absent, unreadable, or `elite` means **elite**" in text


def test_claude_md_routes_finish_and_habit_goals():
    text = _claude_md()
    assert "하프 완주하고 싶어" in text
    assert "주 3번 꾸준히 뛰고 싶어" in text
    # the existing elite example survives untouched
    assert "풀코스 sub-3:30 만들고 싶어" in text
    assert "10K 50분인데 45분 가고 싶어, 16주 남음" in text


if __name__ == "__main__":
    passed = failed = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"  PASS  {_name}")
                passed += 1
            except Exception as exc:  # noqa: BLE001
                import traceback
                print(f"  FAIL  {_name}: {exc}")
                traceback.print_exc()
                failed += 1
    print(f"\nagent_prompts: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
