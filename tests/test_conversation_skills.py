from backend.voice.objective_engine import ObjectiveEngine
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.resistance_tracker import ResistanceTracker


def test_turn_count_cannot_fill_missing_discovery():
    ctx = CallContext(address_known=True, intent_locked=True, motivation_signals=["relocation"], turn_count=40)
    assert ObjectiveEngine().decide(ctx) == "STAGE_2_DISCOVER"


def test_bob_stage_cannot_skip_missing_seller_facts():
    assert ObjectiveEngine().decide(CallContext(bob_phase="WRAP")) == "STAGE_1_QUALIFY"


def test_short_answers_alone_cannot_end_conversation():
    ctx = CallContext(fatigue_level="CRITICAL", turn_count=10)
    assert ObjectiveEngine().decide(ctx) != "STAGE_5_WRAP"


def test_one_rejection_is_not_counted_repeatedly():
    ctx = CallContext()
    tracker = ResistanceTracker(ctx)
    tracker._update_resistance("Not interested")
    assert tracker._score == 1


def test_seller_can_retract_selling_intent():
    ctx = CallContext(intent_locked=True)
    ContextTrackerProcessor(ctx)._analyze("Actually I'm not selling anymore")
    assert not ctx.intent_locked


def test_positive_condition_is_a_known_answer_not_a_missing_defect():
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze("The house is in good condition, no repairs needed")
    assert getattr(ctx, "condition_known", False)


def test_price_correction_in_same_utterance_uses_latest_value():
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze("I was asking $220k, but now I'm asking $210k")
    assert ctx.last_price_mentioned == 21000000


def test_condition_correction_removes_old_roof_problem():
    ctx = CallContext(property_issues=["roof"])
    ContextTrackerProcessor(ctx)._analyze("Actually the roof is fine now")
    assert "roof" not in ctx.property_issues


def test_numeric_answer_is_bound_to_last_question():
    from backend.voice.conversation_policy import remember_assistant_turn
    ctx = CallContext()
    tracker = ContextTrackerProcessor(ctx)
    remember_assistant_turn(ctx, "What price are you asking?")
    tracker._analyze("210000")
    assert ctx.last_price_mentioned == 21000000
    remember_assistant_turn(ctx, "How much do you owe on the mortgage?")
    tracker._analyze("150000")
    assert ctx.last_price_mentioned == 21000000


def test_a_yes_to_good_time_is_not_owner_confirmation():
    from backend.voice.conversation_policy import remember_assistant_turn
    ctx = CallContext(is_outbound=True)
    remember_assistant_turn(ctx, "Is this a good time?")
    assert not ctx.awaiting_owner_confirmation


def test_direct_question_overrides_hot_lead_and_booked_state():
    from backend.voice.conversation_policy import plan_turn
    ctx = CallContext(deal_heat=10, appointment_set=True)
    plan = plan_turn(ctx, "Are there any fees?")
    assert plan.goal == "answer"
    assert plan.question_limit == 0


def test_completed_facts_do_not_get_reasked():
    from backend.voice.conversation_policy import plan_turn
    ctx = CallContext(owner_confirmed=True, intent_locked=True, motivation_signals=["relocation"], timeline_mentioned="next month", condition_known=True)
    assert plan_turn(ctx, "That covers it").goal == "walkthrough"


def test_loan_negation_does_not_erase_roof_problem():
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze("No loan but the roof is leaking")
    assert "roof" in ctx.property_issues


import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from backend.voice.conversation_policy import plan_turn, remember_assistant_turn


@pytest.mark.parametrize("seller,goal", [
    ("Are you a real person?", "identity"),
    ("Are you human?", "identity"),
    ("Can I talk to a real person?", "human"),
    ("I'm not selling until next month", "space"),
    ("Not selling unless the price is right", "space"),
    ("Not selling", "decline"),
    ("Stop calling me", "stop"),
    ("Let me finish", "wait"),
    ("I need to think about it", "space"),
    ("Slow down", "repair"),
    ("How did you get my number?", "answer"),
    ("You have the wrong number", "wrong_person"),
    ("I'm driving", "callback"),
])
@pytest.mark.parametrize("variant", ["plain", "uppercase", "curly"])
def test_request_priority_under_pressure(seller, goal, variant):
    seller = seller.upper() if variant == "uppercase" else seller.replace("'", "’") if variant == "curly" else seller
    ctx = CallContext(appointment_set=True, deal_heat=10, fatigue_level="CRITICAL")
    assert plan_turn(ctx, seller).goal == goal


def test_yes_to_later_question_does_not_accept_earlier_walkthrough():
    ctx = CallContext()
    tracker = ContextTrackerProcessor(ctx)
    remember_assistant_turn(ctx, "Would a walkthrough help?")
    remember_assistant_turn(ctx, "Is this a good time?")
    tracker._analyze("Yes")
    assert not ctx.pre_close_done


def test_replay_suite_is_explicitly_not_model_or_audio_evidence():
    from backend.voice.conversation_replay import run_replays
    result = run_replays()
    assert result["failed"] == 0
    assert result["model_generated_conversations"] == 0
    assert all(not run["appointment_booked"] for run in result["results"])


@pytest.mark.asyncio
async def test_turn_reset_clears_old_instruction_before_new_policy():
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from backend.voice.conversation_policy import ConversationTurnReset, ConversationPolicyProcessor
    ctx = CallContext(runtime_instruction="Push for a visit now", response_guidance="Old answer")
    frame = TranscriptionFrame("Are there any fees?", "seller", "now")
    reset = ConversationTurnReset(ctx)
    policy = ConversationPolicyProcessor(ctx)
    reset.push_frame = AsyncMock()
    policy.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await reset.process_frame(frame, FrameDirection.DOWNSTREAM)
        assert ctx.runtime_instruction is None
        assert ctx.response_guidance == ""
        await policy.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert ctx.response_goal == "answer"
    assert "Ask at most 0" in ctx.build_context_prefix()
    policy.push_frame.assert_awaited_once_with(frame, FrameDirection.DOWNSTREAM)


@pytest.mark.asyncio
async def test_simulator_does_not_treat_confirmed_word_as_booking_or_end():
    from backend.voice.simulator import run_simulation
    replies = ["What does an appointment involve?", "Nothing is confirmed yet.", "Not interested", "Thanks for telling me. Goodbye."]
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=[SimpleNamespace(content=[SimpleNamespace(text=text)]) for text in replies])))
    result = await run_simulation(client=client, grade=False)
    assert client.messages.create.await_count == 4
    assert not result["appointment_booked"]
    assert result["end_reason"] == "decline"
    assert not result["persisted"]
    assert "automated assistant" in result["transcript"].splitlines()[0]
    assert "RESPONSE PRIORITY: answer" in client.messages.create.call_args_list[1].kwargs["system"]


@pytest.mark.asyncio
async def test_simulator_limits_estimated_minute_without_claiming_audio():
    from backend.voice.simulator import run_simulation
    response = SimpleNamespace(content=[SimpleNamespace(text="a realistic sentence " * 15)])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
    result = await run_simulation(client=client, grade=False, duration_seconds=60)
    assert result["end_reason"] == "estimated_duration_limit"
    assert result["turns"] < 12
    assert not result["audio_tested"]
    assert not result["tool_execution_tested"]


@pytest.mark.asyncio
async def test_simulation_grading_never_persists_or_alerts_even_legacy_save_flag():
    from backend.voice.simulator import run_simulation
    response = SimpleNamespace(content=[SimpleNamespace(text="Not interested")])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
    with patch("backend.voice.simulator.grade_call", new=AsyncMock(return_value={})) as grader:
        await run_simulation(client=client, save_to_db=True)
    assert grader.call_args.kwargs["persist"] is False


@pytest.mark.parametrize("answer", ["Maybe", "Yes but only if you pay $210k", "Sure if my wife agrees", "Possibly", "It depends"])
def test_conditional_agreement_is_not_walkthrough_consent(answer):
    ctx = CallContext()
    remember_assistant_turn(ctx, "Would a walkthrough help?")
    ContextTrackerProcessor(ctx)._analyze(answer)
    assert not ctx.pre_close_done


@pytest.mark.asyncio
async def test_nonpersistent_grading_cannot_notify_owner():
    from backend.qa import grader
    from backend.lib import db
    scores = {"qualification": 2, "offer_quality": None, "objection_handling": None, "appointment_booking": None, "tone": 2, "goal_completion": 2, "call_summary": "Poor simulated conversation", "failures": ["Repeated questions"]}
    response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_grades", input=scores)])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))
    with patch.object(grader, "_get_client", return_value=client), patch.object(db, "save_call_grade") as save, patch.object(grader, "send_alert_to_owner") as alert:
        result = await grader.grade_call("A simulated conversation. " * 4, "simulation", "sim_test", persist=False)
    assert result["overall_score"] == 2
    save.assert_not_called()
    alert.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("question,topic", [("What price are you asking?", "price"), ("Would a walkthrough help?", "walkthrough"), ("Am I speaking with Alex?", "owner"), ("How much do you owe on the mortgage?", "mortgage")])
@pytest.mark.parametrize("chunk_size", [1, 2, 100])
async def test_spoken_question_survives_provider_word_chunks(question, topic, chunk_size):
    from backend.voice.agent import TranscriptJournal
    from pipecat.frames.frames import TTSTextFrame
    from pipecat.processors.frame_processor import FrameDirection
    ctx = CallContext()
    journal = TranscriptJournal(ctx, "assistant")
    journal.push_frame = AsyncMock()
    words = question.split()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        for offset in range(0, len(words), chunk_size):
            await journal.process_frame(TTSTextFrame(" ".join(words[offset:offset+chunk_size]), aggregated_by="word"), FrameDirection.DOWNSTREAM)
    assert ctx.last_question_topic == topic
    assert ctx._walkthrough_asked == (topic == "walkthrough")


@pytest.mark.asyncio
async def test_interrupted_question_is_not_joined_to_next_response():
    from backend.voice.agent import TranscriptJournal
    from pipecat.frames.frames import TTSTextFrame, UserStartedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection
    ctx = CallContext()
    journal = TranscriptJournal(ctx, "assistant")
    journal.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await journal.process_frame(TTSTextFrame("What price are you", aggregated_by="word"), FrameDirection.DOWNSTREAM)
        await journal.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await journal.process_frame(TTSTextFrame("Would a walkthrough help?", aggregated_by="sentence"), FrameDirection.DOWNSTREAM)
    assert ctx.last_question_topic == "walkthrough"


@pytest.mark.parametrize("timing", ["Next month", "In 45 days", "Within 2 weeks", "No rush", "This month"])
def test_common_timing_answers_are_remembered(timing):
    ctx = CallContext()
    ContextTrackerProcessor(ctx)._analyze(timing)
    assert ctx.timeline_mentioned


def test_conditional_sale_does_not_erase_existing_interest():
    ctx = CallContext(intent_locked=True)
    ContextTrackerProcessor(ctx)._analyze("I'm not selling until next month")
    assert ctx.intent_locked


@pytest.mark.asyncio
async def test_identity_processor_answers_again_after_first_disclosure():
    from backend.voice.processors.ai_identity import AIIdentityProcessor
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    ctx = CallContext()
    identity = AIIdentityProcessor(ctx)
    identity.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        for text in ("Are you AI?", "Are you a robot?"):
            ctx.runtime_instruction = None
            await identity.process_frame(TranscriptionFrame(text, "seller", "now"), FrameDirection.DOWNSTREAM)
            assert "automated assistant" in ctx.runtime_instruction
