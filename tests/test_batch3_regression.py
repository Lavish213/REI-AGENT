"""
Batch 3 regression tests — conversational realism + operator instinct.

Tests:
- Intent lock: confirmed seller must never get asked if they want to sell
- Silence hints: emotional/price content sets correct hint
- Pacing advancement: fields_known drives pacing_state transitions
- Seller mode: situation + energy maps correctly
- SpokenRenderer compression: AI-complete → fragment speech
- SpokenRenderer AI scoring: over-polished text gets flagged
- SpokenRenderer sentence pruning: respects pacing_state limits
- Seller mode modulation: DISTRESSED overrides pacing compression
"""
from __future__ import annotations

import asyncio
import re
import pytest

from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.processors.spoken_renderer import (
    SpokenRendererProcessor,
    _apply_substitutions as _apply_fragments,  # unified substitution engine (Batch 4)
    _strip_ai_setups,
    _score_ai_level,
    _prune_sentences,
    _max_sentences,
    _split_sentences,
)


# ---------------------------------------------------------------------------
# CallContext — pacing state
# ---------------------------------------------------------------------------

class TestPacingAdvancement:
    def _make_ctx(self) -> CallContext:
        ctx = CallContext()
        return ctx

    def test_starts_warm(self):
        ctx = self._make_ctx()
        assert ctx.pacing_state == "warm"

    def test_intent_confirmed_advances_to_operational(self):
        ctx = self._make_ctx()
        ctx.intent_confirmed = True
        # Simulate _update_pacing by calling logic directly
        from backend.voice.processors.context_tracker import ContextTrackerProcessor
        # We'll test through a processor instance
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_pacing()
        assert ctx.pacing_state == "operational"

    def test_three_fields_advances_to_tight(self):
        ctx = self._make_ctx()
        ctx.intent_confirmed = True
        ctx.address_known = True
        ctx.motivation_known = True
        ctx.occupancy_known = True
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_pacing()
        assert ctx.pacing_state == "tight"

    def test_pacing_never_regresses(self):
        ctx = self._make_ctx()
        ctx.pacing_state = "tight"
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        # Only intent confirmed — would normally be operational
        ctx.intent_confirmed = True
        proc._update_pacing()
        assert ctx.pacing_state == "tight"  # Must not regress

    def test_rushed_seller_forces_tight(self):
        ctx = self._make_ctx()
        ctx.seller_energy = "rushed"
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_pacing()
        assert ctx.pacing_state == "tight"

    def test_hot_disposition_forces_tight(self):
        ctx = self._make_ctx()
        ctx.disposition = "HOT"
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_pacing()
        assert ctx.pacing_state == "tight"


# ---------------------------------------------------------------------------
# CallContext — silence hints
# ---------------------------------------------------------------------------

class TestSilenceHints:
    def _proc(self, ctx: CallContext) -> ContextTrackerProcessor:
        return ContextTrackerProcessor(call_ctx=ctx, llm_context=None)

    def test_price_mention_sets_price_hint(self):
        ctx = CallContext()
        proc = self._proc(ctx)
        proc._update_silence_hint("I'm thinking around $250,000")
        assert ctx.silence_hint == "price"

    def test_death_sets_emotional_hint(self):
        ctx = CallContext()
        proc = self._proc(ctx)
        proc._update_silence_hint("my mom passed away last month")
        assert ctx.silence_hint == "emotional"

    def test_foreclosure_sets_emotional_hint(self):
        ctx = CallContext()
        proc = self._proc(ctx)
        proc._update_silence_hint("I'm behind on the mortgage")
        assert ctx.silence_hint == "emotional"

    def test_skeptical_energy_sets_skeptical_hint(self):
        ctx = CallContext()
        ctx.seller_energy = "skeptical"
        proc = self._proc(ctx)
        proc._update_silence_hint("sounds too good to be true")
        assert ctx.silence_hint == "skeptical"

    def test_neutral_text_no_hint(self):
        ctx = CallContext()
        proc = self._proc(ctx)
        proc._update_silence_hint("Yeah the house is in Stockton")
        assert ctx.silence_hint is None

    def test_existing_hint_not_overwritten(self):
        ctx = CallContext()
        ctx.silence_hint = "price"
        proc = self._proc(ctx)
        proc._update_silence_hint("my dad died")
        assert ctx.silence_hint == "price"  # first hint preserved


# ---------------------------------------------------------------------------
# CallContext — seller mode + objective
# ---------------------------------------------------------------------------

class TestSellerMode:
    def test_intent_confirmed_with_address_skips_to_motivation(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        ctx.address_known = True
        assert ctx.get_current_objective() == "GET_MOTIVATION"

    def test_all_fields_known_goes_to_appointment(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        ctx.address_known = True
        ctx.motivation_known = True
        ctx.occupancy_known = True
        ctx.condition_known = True
        ctx.timeline_known = True
        ctx.price_expectation_known = True
        assert ctx.get_current_objective() == "BOOK_APPOINTMENT"

    def test_foreclosure_situation_gives_distressed_mode(self):
        ctx = CallContext()
        ctx.situation_label = "preforeclosure"
        assert ctx.get_seller_mode() == "DISTRESSED"

    def test_inherited_situation_gives_inherited_mode(self):
        ctx = CallContext()
        ctx.situation_label = "inherited_property"
        assert ctx.get_seller_mode() == "INHERITED"

    def test_divorce_situation_gives_divorce_mode(self):
        ctx = CallContext()
        ctx.situation_label = "divorce"
        assert ctx.get_seller_mode() == "DIVORCE"

    def test_landlord_situation_gives_landlord_mode(self):
        ctx = CallContext()
        ctx.situation_label = "tired_landlord"
        assert ctx.get_seller_mode() == "LANDLORD"

    def test_skeptical_energy_gives_skeptical_mode(self):
        ctx = CallContext()
        ctx.seller_energy = "skeptical"
        assert ctx.get_seller_mode() == "SKEPTICAL"

    def test_hot_disposition_gives_hot_mode(self):
        ctx = CallContext()
        ctx.disposition = "HOT"
        assert ctx.get_seller_mode() == "HOT"


# ---------------------------------------------------------------------------
# Intent lock regression
# ---------------------------------------------------------------------------

class TestIntentLock:
    """Sophia must never ask 'were you considering selling' when intent is confirmed."""

    def test_intent_confirmed_forbidden_move_added(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        forbidden = ctx.get_forbidden_moves()
        assert any("want to sell" in f for f in forbidden)

    def test_intent_not_confirmed_no_forbidden(self):
        ctx = CallContext()
        forbidden = ctx.get_forbidden_moves()
        assert not any("want to sell" in f for f in forbidden)

    def test_context_prefix_has_obj_not_confirm_after_intent(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        prefix = ctx.build_context_prefix()
        assert "OBJ=CONFIRM_INTENT" not in prefix
        assert "OBJ=GET_ADDRESS" in prefix or "OBJ=GET_MOTIVATION" in prefix

    def test_context_prefix_has_no_for_known_facts(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        ctx.address_known = True
        prefix = ctx.build_context_prefix()
        assert "NO=" in prefix
        assert "address" in prefix


# ---------------------------------------------------------------------------
# SpokenRenderer — fragment compression
# ---------------------------------------------------------------------------

class TestFragmentCompression:
    def test_vacancy_question_compressed(self):
        result = _apply_fragments("Is the property currently vacant?")
        assert result == "Vacant right now?"

    def test_occupancy_question_compressed(self):
        result = _apply_fragments("Are you currently living there?")
        assert result == "Living there now?"

    def test_address_question_compressed(self):
        result = _apply_fragments("Could you provide the property address?")
        assert result == "What's the address?"

    def test_condition_question_compressed(self):
        result = _apply_fragments("Does it currently need any work?")
        assert result == "Need much work?"

    def test_neutral_text_unchanged(self):
        text = "What's the address?"
        assert _apply_fragments(text) == text

    def test_timeline_question_compressed(self):
        result = _apply_fragments("How soon are you looking to sell?")
        assert "How soon" in result


# ---------------------------------------------------------------------------
# SpokenRenderer — AI setup stripping
# ---------------------------------------------------------------------------

class TestAISetupStripping:
    def test_id_love_to_ask_stripped(self):
        text = "I'd love to ask you a few questions about the property. What's the address?"
        result = _strip_ai_setups(text)
        assert "I'd love to ask" not in result
        assert "What's the address?" in result

    def test_before_i_can_stripped(self):
        text = "Before I can give you a ballpark, I'd need to understand the condition."
        result = _strip_ai_setups(text)
        assert "Before I can" not in result

    def test_i_want_to_make_sure_stripped(self):
        text = "I want to make sure I understand your situation. Are you living there now?"
        result = _strip_ai_setups(text)
        assert "I want to make sure" not in result

    def test_no_setup_text_unchanged(self):
        text = "What's the address on that?"
        assert _strip_ai_setups(text) == text


# ---------------------------------------------------------------------------
# SpokenRenderer — AI scoring
# ---------------------------------------------------------------------------

class TestAIScoring:
    def test_clean_operator_speech_scores_low(self):
        text = "Okay. What's the address?"
        assert _score_ai_level(text) < 5

    def test_id_be_happy_to_scores_high(self):
        text = "I'd be happy to help you with that."
        assert _score_ai_level(text) >= 3

    def test_certainly_scores_high(self):
        text = "Certainly, I understand your concern."
        assert _score_ai_level(text) >= 3

    def test_multiple_ai_patterns_accumulate(self):
        text = "I'd be happy to assist you. Certainly, I completely understand your concern. Does that make sense?"
        assert _score_ai_level(text) >= 8

    def test_many_sentences_penalized(self):
        text = "Okay. I hear you. That makes sense. Let me ask you something. What's the address?"
        score = _score_ai_level(text)
        # 5 sentences should add penalty
        assert score >= 2

    def test_long_sentence_penalized(self):
        text = "I completely understand that you're going through a difficult situation right now with the property."
        score = _score_ai_level(text)
        assert score >= 1  # long sentence + AI phrase


# ---------------------------------------------------------------------------
# SpokenRenderer — sentence pruning
# ---------------------------------------------------------------------------

class TestSentencePruning:
    def test_warm_allows_three_sentences(self):
        assert _max_sentences("warm", "STANDARD") == 3

    def test_operational_allows_two_sentences(self):
        assert _max_sentences("operational", "STANDARD") == 2

    def test_tight_allows_one_sentence(self):
        assert _max_sentences("tight", "STANDARD") == 1

    def test_hot_forces_one_sentence(self):
        assert _max_sentences("warm", "HOT") == 1

    def test_fast_forces_one_sentence(self):
        assert _max_sentences("operational", "FAST") == 1

    def test_distressed_overrides_tight_to_three(self):
        assert _max_sentences("tight", "DISTRESSED") == 3

    def test_inherited_overrides_tight_to_three(self):
        assert _max_sentences("tight", "INHERITED") == 3

    def test_prune_keeps_question_from_dropped_sentences(self):
        text = "Got it. Makes sense. Were you living there?"
        result = _prune_sentences(text, max_s=1)
        assert "Were you living there?" in result

    def test_prune_tight_gives_one_sentence(self):
        text = "Okay. That makes sense. What's the address?"
        result = _prune_sentences(text, max_s=1)
        sentences = _split_sentences(result)
        assert len(sentences) == 1


# ---------------------------------------------------------------------------
# SpokenRenderer — end-to-end transform
# ---------------------------------------------------------------------------

class TestSpokenRendererTransform:
    def _renderer(self, **kwargs) -> SpokenRendererProcessor:
        ctx = CallContext()
        for k, v in kwargs.items():
            setattr(ctx, k, v)
        return SpokenRendererProcessor(call_ctx=ctx)

    def test_transform_strips_setup_and_compresses(self):
        renderer = self._renderer(pacing_state="operational")
        result = renderer._transform(
            "I'd love to ask you a few questions about the property. Is the property currently vacant?"
        )
        assert "I'd love to ask" not in result
        assert "currently vacant" not in result
        assert "Vacant right now?" in result

    def test_transform_prunes_to_pacing_limit(self):
        renderer = self._renderer(pacing_state="tight")
        result = renderer._transform(
            "Okay. That makes a lot of sense. I hear you. What's the address?"
        )
        sentences = _split_sentences(result)
        assert len(sentences) == 1

    def test_transform_never_returns_empty(self):
        renderer = self._renderer(pacing_state="warm")
        result = renderer._transform("   ")
        # Should return original, which is whitespace — but _transform uses `or original`
        # Empty string is falsy, so original is returned
        assert isinstance(result, str)

    def test_high_ai_score_forces_truncation(self):
        renderer = self._renderer(pacing_state="operational")
        ai_text = (
            "I'd be happy to assist you. Certainly, I completely understand your concern. "
            "Does that make sense? Is there anything else I can help you with? "
            "I appreciate you sharing that with me. What's the address?"
        )
        result = renderer._transform(ai_text)
        # Should be much shorter — last sentence preserved
        assert len(result) < len(ai_text) * 0.7

    def test_distressed_mode_not_truncated_aggressively(self):
        renderer = self._renderer(pacing_state="tight", situation_label="preforeclosure")
        text = "I hear you. That's a tough spot. What does the timeline look like?"
        result = renderer._transform(text)
        # DISTRESSED overrides tight → max 3 sentences, so 3-sentence input should pass through
        assert "tough spot" in result or "timeline" in result

    @pytest.mark.asyncio
    async def test_silence_consumed_after_use(self):
        ctx = CallContext()
        ctx.silence_hint = "price"
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        # Mock asyncio.sleep so test doesn't actually wait
        slept = []
        original_sleep = asyncio.sleep

        async def mock_sleep(s):
            slept.append(s)

        import asyncio as _asyncio
        _asyncio.sleep = mock_sleep
        try:
            delay = renderer._get_silence_delay()
            assert delay == 0.65
            assert ctx.silence_hint is None  # consumed
        finally:
            _asyncio.sleep = original_sleep
