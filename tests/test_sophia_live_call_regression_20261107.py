from backend.voice.conversation_policy import plan_turn, remember_assistant_turn
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.runtime_orchestrator import RuntimeOrchestrator


def test_vague_motivation_answer_is_repaired_instead_of_pitched():
    ctx = CallContext(owner_confirmed=True, intent_locked=True)
    remember_assistant_turn(ctx, "What's got you thinking about the property right now?")

    plan = plan_turn(ctx, "Silly")

    assert ctx.last_question_topic == "motivation"
    assert plan.goal == "clarify_vague"
    assert "Do not pitch" in plan.guidance


def test_high_heat_cannot_skip_missing_discovery():
    ctx = CallContext(
        owner_confirmed=True,
        intent_locked=True,
        deal_heat=10,
        momentum_score=10,
    )

    decision = RuntimeOrchestrator().decide(ctx)

    assert decision.objective_override is None


def test_generic_walkthrough_yes_does_not_book_without_discovery():
    ctx = CallContext(owner_confirmed=True, intent_locked=True)
    remember_assistant_turn(ctx, "Would a walkthrough be useful?")

    ContextTrackerProcessor(ctx)._analyze("Sure")

    assert not ctx.pre_close_done
    assert plan_turn(ctx, "Sure").goal != "schedule"


def test_complete_discovery_can_advance_to_walkthrough():
    ctx = CallContext(
        owner_confirmed=True,
        intent_locked=True,
        motivation_signals=["relocation"],
        timeline_mentioned="next month",
        condition_known=True,
        deal_heat=10,
        momentum_score=10,
    )

    decision = RuntimeOrchestrator().decide(ctx)

    assert decision.objective_override == "BOOK_APPOINTMENT"


