import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestInterruptionProcessor:
    def test_interruption_ack_pool_not_empty(self):
        from backend.voice.processors.interruption import INTERRUPTION_ACKNOWLEDGMENTS
        assert len(INTERRUPTION_ACKNOWLEDGMENTS) > 0
        assert all(isinstance(a, str) and len(a) > 0 for a in INTERRUPTION_ACKNOWLEDGMENTS)

    def test_interruption_ack_varied(self):
        from backend.voice.processors.interruption import INTERRUPTION_ACKNOWLEDGMENTS
        assert len(set(INTERRUPTION_ACKNOWLEDGMENTS)) >= 3

    @pytest.mark.asyncio
    async def test_interruption_processor_instantiates(self):
        from backend.voice.processors.interruption import InterruptionAckProcessor
        proc = InterruptionAckProcessor()
        assert proc is not None
        assert proc._last_ack is None


class TestAIIdentityProcessor:
    @pytest.mark.asyncio
    async def test_ai_identity_processor_instantiates(self):
        from backend.voice.processors.ai_identity import AIIdentityProcessor
        proc = AIIdentityProcessor()
        assert proc is not None
        assert proc._disclosed is False

    def test_identity_patterns_match_common_questions(self):
        import re
        from backend.voice.processors.ai_identity import _AI_QUESTION as _IDENTITY_PATTERNS
        questions = [
            "are you a robot",
            "is this a bot",
            "are you real",
            "am i talking to a computer",
            "real person",
            "are you an AI",
        ]
        for q in questions:
            assert _IDENTITY_PATTERNS.search(q), f"Pattern should match: {q!r}"

    def test_identity_patterns_no_false_positives(self):
        import re
        from backend.voice.processors.ai_identity import _AI_QUESTION as _IDENTITY_PATTERNS
        normal = [
            "I want to sell my house",
            "what's your offer",
            "how does this work",
            "when can you come by",
        ]
        for text in normal:
            assert not _IDENTITY_PATTERNS.search(text), f"False positive: {text!r}"


class TestEmotionProcessor:
    @pytest.mark.parametrize("text,expected", [
        ("my husband passed away last month", "GRIEVING"),
        ("we're going through a divorce", "DISTRESSED"),
        ("I'm behind on the mortgage", "DISTRESSED"),
        ("I don't know what to do", "OVERWHELMED"),
        ("when can you come take a look", "EXCITED"),
        ("the home has a new roof", "NEUTRAL"),
    ])
    def test_current_emotion_engine(self, text, expected):
        from backend.voice.emotional_state_engine import EmotionalStateEngine
        from backend.voice.processors.context_tracker import CallContext
        ctx = CallContext()
        EmotionalStateEngine(ctx)._update_emotional_state(text)
        assert ctx.emotional_state == expected


class TestFairHousingFilter:
    def test_demographic_steering_detected(self):
        from backend.voice.processors.fair_housing import _is_fair_housing_violation
        assert _is_fair_housing_violation("that's a good neighborhood with mostly white families")
        assert _is_fair_housing_violation("crime rate is high because of those people")
        assert _is_fair_housing_violation("changing neighborhood")

    def test_neutral_property_talk_passes(self):
        from backend.voice.processors.fair_housing import _is_fair_housing_violation
        assert not _is_fair_housing_violation("the property has 3 bedrooms and 2 baths")
        assert not _is_fair_housing_violation("we'd be looking at around 180 to 195 thousand")
        assert not _is_fair_housing_violation("the area has a solid market for what we do")


class TestSellerMemory:
    def test_call_summaries_capped_at_10(self):
        from backend.voice.memory import SellerMemory
        m = SellerMemory("test-lead")
        for i in range(15):
            m.add_call_summary(f"Call {i} summary text")
        assert len(m.call_summaries) == 10
        assert m.call_summaries[0] == "Call 5 summary text"

    def test_to_prompt_context_empty_returns_empty_string(self):
        from backend.voice.memory import SellerMemory
        m = SellerMemory("test-lead")
        assert m.to_prompt_context() == ""

    def test_to_prompt_context_with_data(self):
        from backend.voice.memory import SellerMemory
        m = SellerMemory("test-lead")
        m.add_call_summary("Last call: seller mentioned divorce, wants 250k")
        m.price_floor = 25000000
        m.hot_topics = ["divorce", "timeline urgent"]
        m.motivation_level = 8
        ctx = m.to_prompt_context()
        assert "SELLER MEMORY" in ctx
        assert "$250,000" in ctx
        assert "divorce" in ctx
        assert "8/10" in ctx

    def test_price_floor_formats_correctly(self):
        from backend.voice.memory import SellerMemory
        m = SellerMemory("test-lead")
        m.call_summaries = ["placeholder"]
        m.price_floor = 18500000
        ctx = m.to_prompt_context()
        assert "$185,000" in ctx


class TestSentenceStreamer:
    @pytest.mark.asyncio
    async def test_hard_boundary_flush_on_period(self):
        from backend.voice.processors.sentence_streamer import SentenceStreamProcessor
        from pipecat.frames.frames import LLMTextFrame, TTSTextFrame, LLMFullResponseEndFrame
        from pipecat.processors.frame_processor import FrameDirection

        flushed = []

        proc = SentenceStreamProcessor()
        orig_push = proc.push_frame

        async def capture_push(frame, direction=FrameDirection.DOWNSTREAM):
            if isinstance(frame, TTSTextFrame):
                flushed.append(frame.text)
            await orig_push(frame, direction)

        proc.push_frame = capture_push

        from pipecat.frames.frames import LLMTextFrame
        await proc.process_frame(LLMTextFrame(text="Hey there. "), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMTextFrame(text="How are you?"), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

        assert len(flushed) >= 1
        combined = " ".join(flushed)
        assert "Hey there" in combined
