import pytest

from backend.voice.conversation_policy import discovery_ready, plan_turn, remember_assistant_turn
from backend.voice.objective_engine import ObjectiveEngine
from backend.voice.processors.ai_softener import AISoftenerProcessor
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor


@pytest.mark.parametrize(
    "answer",
    [
        "I'm just curious what my options are",
        "I'm exploring whether selling makes sense",
        "No big rush, I wanted to learn how this works",
    ],
)
def test_calm_motivation_answer_is_accepted_without_hunting_for_distress(answer):
    ctx = CallContext(owner_confirmed=True, intent_locked=True)
    remember_assistant_turn(ctx, "What's prompting you to consider selling?")

    ContextTrackerProcessor(ctx)._analyze(answer)

    assert ctx.motivation_known
    assert plan_turn(ctx, answer).goal == "timeline"


def test_vague_motivation_answer_still_gets_one_simpler_repair():
    ctx = CallContext(owner_confirmed=True, intent_locked=True)
    remember_assistant_turn(ctx, "What's prompting you to consider selling?")

    ContextTrackerProcessor(ctx)._analyze("I don't know")

    assert not ctx.motivation_known
    assert plan_turn(ctx, "I don't know").goal == "clarify_vague"


def test_completed_calm_discovery_can_reach_walkthrough():
    ctx = CallContext(
        owner_confirmed=True,
        intent_locked=True,
        motivation_known=True,
        timeline_mentioned="no rush",
        condition_known=True,
    )

    assert discovery_ready(ctx)
    assert ObjectiveEngine().decide(ctx) == "STAGE_3_PRECLOSE"
    assert plan_turn(ctx, "That is about it").goal == "walkthrough"


def test_context_prefix_supplies_safe_specific_facts_without_raw_story():
    ctx = CallContext(
        motivation_signals=["relocation"],
        motivation_known=True,
        timeline_mentioned="next month",
        property_issues=["roof"],
    )

    prefix = ctx.build_context_prefix()

    assert "seller reason category: relocation" in prefix
    assert "preferred timing: next month" in prefix
    assert "condition topics: roof" in prefix
    assert "Use one relevant fact naturally" in prefix


def test_runtime_prompt_bans_canned_openers_and_distress_hunting():
    from backend.voice.agent import _load_system_prompt

    prompt = _load_system_prompt({"property_context_str": "Caller and property verified."})

    assert "never dig for distress" in prompt
    assert "Avoid canned turn openers" in prompt
    assert "at most one simple question" in prompt


def test_live_pipeline_refuses_to_start_without_ai_softener():
    from backend.voice.agent import _assert_pipeline_safety

    processors = [
        type("ComplianceOutputFilter", (), {})(),
        type("FairHousingFilter", (), {})(),
        type("SentenceStreamProcessor", (), {})(),
    ]

    with pytest.raises(RuntimeError, match="AISoftenerProcessor"):
        _assert_pipeline_safety(processors)


def test_internal_qa_property_label_is_never_spoken():
    processor = AISoftenerProcessor()

    spoken = processor._soften(
        "So November 11th at 12:30 PM at the QA TEST ONLY - DO NOT CONTACT property in Stockton."
    )

    assert "QA TEST" not in spoken
    assert "DO NOT CONTACT" not in spoken
    assert "the property in Stockton" in spoken
