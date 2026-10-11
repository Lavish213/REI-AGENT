from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import TranscriptionFrame, InterimTranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from backend.voice.conversation_policy import plan_turn, ConversationPolicyProcessor
from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.processors.speech_understanding import SpeechUnderstandingProcessor, transcript_confidence


REQUESTS = [
    ("I'm hard of hearing", "repair"),
    ("Please speak louder", "repair"),
    ("Speak up", "repair"),
    ("You are too quiet", "repair"),
    ("I have a hearing aid", "repair"),
    ("Could you talk slowly", "repair"),
    ("Can you slow down", "repair"),
    ("You're muffled", "repair"),
    ("You're breaking up", "repair"),
    ("There's background noise", "repair"),
    ("It's a bad connection", "repair"),
    ("I missed the last bit", "repair"),
    ("I can't make that out", "repair"),
    ("I didn't understand", "repair"),
    ("I don't understand what that means", "repair"),
    ("I ain't heard you", "repair"),
    ("Pardon", "repair"),
    ("Huh", "repair"),
    ("Come again", "repair"),
    ("No te escucho", "repair"),
    ("No entiendo", "repair"),
    ("Más despacio", "repair"),
    ("Uh, tell me what fees you charge", "answer"),
    ("Um, explain the process", "answer"),
    ("Well, how does that work", "answer"),
    ("Hey, what does an offer mean", "answer"),
    ("Tell me how you got my number", "answer"),
    ("Call me tomorrow at three", "callback"),
    ("Call me next week", "callback"),
    ("Call me on Thursday", "callback"),
    ("Call me in two hours", "callback"),
    ("Not interested in a walkthrough, but I do want an offer", "alternative"),
    ("Not interested", "decline"),
    ("Stop calling me", "stop"),
    ("Give me two minutes", "wait"),
    ("Give me 30 seconds", "wait"),
    ("Let me finish", "wait"),
    ("Are you a real person", "identity"),
    ("Can I speak to a real person", "human"),
]


@pytest.mark.parametrize("text,goal", REQUESTS)
@pytest.mark.parametrize("style", ["plain", "uppercase", "curly_apostrophe"])
def test_accessibility_and_transcript_wording(text, goal, style):
    text = text.upper() if style == "uppercase" else text.replace("'", "’") if style == "curly_apostrophe" else text
    assert plan_turn(CallContext(appointment_set=True, deal_heat=10), text).goal == goal


def result(confidence, words=None):
    return {"channel": {"alternatives": [{"confidence": confidence, "words": [{"confidence": score} for score in (words or [])]}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,words,uncertain", [(0.95, [0.9], False), (0.2, [0.9], True), (0.95, [0.1, 0.99], True), (0, [], True), (None, [], False), (float("nan"), [], True), (True, [], True), (1.2, [], True)])
async def test_uncertain_speech_does_not_change_facts(confidence, words, uncertain):
    ctx = CallContext(last_price_mentioned=22000000, _walkthrough_asked=True)
    understanding = SpeechUnderstandingProcessor(ctx)
    understanding.push_frame = AsyncMock()
    frame = TranscriptionFrame("Yes I'm asking $210k and moving next month", "seller", "now", result=result(confidence, words))
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await understanding.process_frame(frame, FrameDirection.DOWNSTREAM)
    ContextTrackerProcessor(ctx)._analyze(frame.text)
    assert ctx.transcript_uncertain is uncertain
    assert ctx.last_price_mentioned == (22000000 if uncertain else 21000000)
    assert ctx.pre_close_done is (not uncertain)
    if uncertain:
        assert plan_turn(ctx, frame.text).goal == "clarify_audio"


@pytest.mark.parametrize("text", ["[inaudible]", "(unintelligible)", "crosstalk", "noise", "static"])
@pytest.mark.asyncio
async def test_unclear_markers_prompt_clarification(text):
    ctx = CallContext()
    processor = SpeechUnderstandingProcessor(ctx)
    processor.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await processor.process_frame(TranscriptionFrame(text, "seller", "now"), FrameDirection.DOWNSTREAM)
    assert plan_turn(ctx, text).goal == "clarify_audio"


@pytest.mark.asyncio
async def test_interim_and_upstream_frames_do_not_overwrite_certainty():
    ctx = CallContext(transcript_uncertain=True)
    processor = SpeechUnderstandingProcessor(ctx)
    processor.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await processor.process_frame(InterimTranscriptionFrame("Yes", "seller", "now"), FrameDirection.DOWNSTREAM)
        await processor.process_frame(TranscriptionFrame("Yes", "seller", "now", result=result(.99)), FrameDirection.UPSTREAM)
    assert ctx.transcript_uncertain


def test_provider_object_confidence_shape():
    provider = SimpleNamespace(channel=SimpleNamespace(alternatives=[SimpleNamespace(confidence=.98, words=[SimpleNamespace(confidence=.2)])]))
    assert transcript_confidence(provider) == (.98, .2, False)


@pytest.mark.asyncio
async def test_repeated_hearing_failure_offers_alternative():
    ctx = CallContext()
    processor = ConversationPolicyProcessor(ctx)
    processor.push_frame = AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        for _ in range(3):
            await processor.process_frame(TranscriptionFrame("I can't hear you", "seller", "now"), FrameDirection.DOWNSTREAM)
    assert "human connection" in ctx.response_guidance
    assert "claim to have changed volume" in ctx.response_guidance


@pytest.mark.asyncio
@pytest.mark.parametrize("text,seconds", [("Hold on",60), ("Give me two minutes",120), ("Give me 30 seconds",30)])
async def test_requested_pause_has_time_before_silence_prompt(text, seconds):
    from backend.voice.silence_handler import _get_timeout
    ctx=CallContext()
    processor=ConversationPolicyProcessor(ctx)
    processor.push_frame=AsyncMock()
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", new=AsyncMock()):
        await processor.process_frame(TranscriptionFrame(text,"seller","now"),FrameDirection.DOWNSTREAM)
    assert _get_timeout("standard",ctx) == seconds


@pytest.mark.parametrize("tool", ["book_appointment", "schedule_callback", "send_followup_sms", "get_offer_range", "transfer_call"])
def test_uncertain_transcript_cannot_trigger_consequential_tools(tool):
    from backend.voice.tools import execute_tool
    ctx=CallContext(transcript_uncertain=True)
    with patch("backend.voice.tools.execution_context.resolve") as resolve:
        assert "not performed" in execute_tool(tool,{},ctx)
    resolve.assert_not_called()


def test_uncertainty_never_blocks_stop_tool():
    from backend.voice.tools import execute_tool
    ctx=CallContext(transcript_uncertain=True)
    assert plan_turn(ctx,"Stop calling me").goal == "stop"
    with patch("backend.voice.tools.execution_context.resolve_for_stop",return_value=SimpleNamespace()),patch("backend.voice.tools._honor_stop_request",return_value="Removed") as stop:
        assert execute_tool("honor_stop_request",{"verbatim":"Stop calling me"},ctx) == "Removed"
    stop.assert_called_once()


@pytest.mark.parametrize("text,field,expected", [
    ("Actually six months instead of next week", "timeline_mentioned", "six months"),
    ("I don't own that house; my brother does", "owner_confirmed", False),
    ("I'm no longer moving; I'm keeping the rental", "intent_locked", False),
])
def test_retracted_facts(text,field,expected):
    ctx=CallContext(owner_confirmed=True,intent_locked=True,timeline_mentioned="next week",motivation_signals=["relocation"])
    ContextTrackerProcessor(ctx)._analyze(text)
    assert getattr(ctx,field) == expected
    if field == "intent_locked":
        assert "relocation" not in ctx.motivation_signals


@pytest.mark.asyncio
async def test_real_worker_preserves_uncertainty_and_recovers_on_clear_repeat():
    import asyncio
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker, PipelineParams
    from pipecat.workers.runner import WorkerRunner
    from pipecat.processors.frame_processor import FrameProcessor
    from backend.voice.conversation_policy import ConversationTurnReset

    ctx = CallContext(last_price_mentioned=22000000)
    observed = []

    class Observe(FrameProcessor):
        def __init__(self):
            super().__init__(enable_direct_mode=True)

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                observed.append((ctx.response_goal, ctx.last_price_mentioned, ctx.transcript_uncertain))
            await self.push_frame(frame, direction)

    worker = PipelineWorker(Pipeline([ConversationTurnReset(ctx), SpeechUnderstandingProcessor(ctx), ContextTrackerProcessor(ctx), ConversationPolicyProcessor(ctx), Observe()]), params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=8000))
    await worker.queue_frames([
        TranscriptionFrame("I'm asking $210k", "seller", "now", result=result(.2)),
        TranscriptionFrame("Actually I'm asking $210k", "seller", "now", result=result(.99)),
        EndFrame(),
    ])
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await asyncio.wait_for(runner.run(), timeout=5)
    assert observed == [("clarify_audio",22000000,True),("correction",21000000,False)]


@pytest.mark.asyncio
async def test_uncertain_transcript_does_not_poison_emotion_or_trust():
    from backend.voice.emotional_state_engine import EmotionalStateEngine
    from backend.voice.trust_tracker import TrustTracker
    ctx=CallContext(transcript_uncertain=True)
    emotion,trust=EmotionalStateEngine(ctx),TrustTracker(ctx)
    emotion.push_frame=AsyncMock()
    trust.push_frame=AsyncMock()
    frame=TranscriptionFrame("My dad passed away, this is a scam", "seller", "now")
    with patch("pipecat.processors.frame_processor.FrameProcessor.process_frame",new=AsyncMock()):
        await emotion.process_frame(frame,FrameDirection.DOWNSTREAM)
        await trust.process_frame(frame,FrameDirection.DOWNSTREAM)
    assert ctx.emotional_state == "NEUTRAL"
    assert ctx.trust_score == 5.0


@pytest.mark.asyncio
async def test_identity_question_does_not_inject_transfer_instruction():
    from backend.voice.processors.analysis_callbacks import AnalysisCallbackProcessor
    ctx=CallContext()
    callback=AnalysisCallbackProcessor(ctx,*[SimpleNamespace() for _ in range(9)])
    await callback._check_phrase_triggers("Are you a real person?")
    assert "automated assistant" in ctx.runtime_instruction
    assert "transfer_call" not in ctx.runtime_instruction


@pytest.mark.parametrize("tool", ["book_appointment","get_offer_range","send_offer_summary"])
def test_denied_ownership_blocks_negotiation_even_with_bound_address(tool):
    from backend.voice.tools import execute_tool
    ctx=CallContext(owner_confirmed=True,address_known=True)
    ContextTrackerProcessor(ctx)._analyze("I don't own that house; my brother does")
    assert plan_turn(ctx,"Okay").goal == "contact"
    with patch("backend.voice.tools.execution_context.resolve") as resolve:
        assert "not performed" in execute_tool(tool,{},ctx)
    resolve.assert_not_called()


def test_poor_connection_does_not_evade_identity_disclosure():
    assert plan_turn(CallContext(transcript_uncertain=True), "Are you AI?").goal == "identity"
