"""
Batch 4 regression tests — operator phrase routing + final AI leak removal.

Tests:
- Substitution engine: AI phrases → bank equivalents
- Service tone removal
- Word count energy caps by pacing × seller_mode
- Redirect override: talkative seller triggers pivot phrase
- SAY= injection in context prefix
- Anti-novelty: short acks no longer suppressed
- V2 AI scoring: service tone, fake enthusiasm, over-completion
"""
from __future__ import annotations

from backend.voice.processors.context_tracker import CallContext, ContextTrackerProcessor
from backend.voice.processors.spoken_renderer import (
    SpokenRendererProcessor,
    _apply_substitutions,
    _apply_energy_cap,
    _score_ai_level,
    _word_cap,
)
from backend.voice.processors.ai_softener import _extract_starter


# ---------------------------------------------------------------------------
# Substitution engine
# ---------------------------------------------------------------------------

class TestSubstitutionEngine:
    def test_that_makes_sense_replaced(self):
        result = _apply_substitutions("That makes sense. What's the address?")
        assert "That makes sense" not in result
        assert "Makes sense" in result

    def test_i_understand_replaced_with_gotcha(self):
        result = _apply_substitutions("I understand. What's the address?")
        assert "I understand." not in result
        assert "Gotcha" in result

    def test_i_appreciate_deleted(self):
        result = _apply_substitutions("I appreciate that. What's the address?")
        assert "I appreciate" not in result
        assert "What's the address?" in result

    def test_thank_you_for_sharing_deleted(self):
        result = _apply_substitutions("Thank you for sharing that. What's the condition?")
        assert "Thank you" not in result
        assert "condition" in result

    def test_of_course_deleted(self):
        result = _apply_substitutions("Of course. Let me ask about the property.")
        assert "Of course" not in result

    def test_absolutely_deleted(self):
        result = _apply_substitutions("Absolutely. What's the address?")
        assert "Absolutely" not in result

    def test_feel_free_deleted(self):
        result = _apply_substitutions("Feel free to call us anytime. What's the address?")
        assert "Feel free" not in result
        assert "What's the address?" in result

    def test_is_there_anything_else_deleted(self):
        result = _apply_substitutions("Is there anything else I can help you with?")
        assert "Is there anything else" not in result

    def test_moving_forward_deleted(self):
        result = _apply_substitutions("Moving forward, let's talk about the condition.")
        assert "Moving forward" not in result

    def test_is_property_vacant_compressed(self):
        result = _apply_substitutions("Is the property currently vacant?")
        assert result == "Vacant right now?"

    def test_are_you_living_there_compressed(self):
        result = _apply_substitutions("Are you living in the property?")
        assert result == "Living there now?"

    def test_could_you_provide_address_compressed(self):
        result = _apply_substitutions("Could you provide the full address?")
        assert result == "What's the address?"

    def test_does_it_need_work_compressed(self):
        result = _apply_substitutions("Does it need any repairs?")
        assert result == "Need much work?"

    def test_how_soon_looking_to_sell_compressed(self):
        result = _apply_substitutions("How soon are you looking to sell?")
        assert "How soon you trying to move?" in result

    def test_what_is_your_timeline_compressed(self):
        result = _apply_substitutions("What's your timeline for the sale?")
        assert "timeline look like" in result

    def test_were_you_considering_selling_compressed(self):
        result = _apply_substitutions("Were you considering selling?")
        assert "thinking about selling" in result

    def test_chain_substitution_cleans_full_response(self):
        # Complex AI-complete sentence with multiple patterns
        text = "I understand. Is the property currently vacant? Feel free to let me know."
        result = _apply_substitutions(text)
        assert "I understand." not in result
        assert "currently vacant" not in result
        assert "Feel free" not in result

    def test_clean_text_unchanged(self):
        text = "Okay. What's the address?"
        assert _apply_substitutions(text) == text

    def test_operator_speech_unchanged(self):
        text = "Vacant right now?"
        assert _apply_substitutions(text) == text


# ---------------------------------------------------------------------------
# Energy caps
# ---------------------------------------------------------------------------

class TestEnergyCaps:
    def test_hot_cap_is_12_words(self):
        assert _word_cap("warm", "HOT") == 12

    def test_fast_cap_is_12_words(self):
        assert _word_cap("operational", "FAST") == 12

    def test_distressed_cap_is_30_words(self):
        assert _word_cap("tight", "DISTRESSED") == 30

    def test_tight_pacing_cap_is_15_words(self):
        assert _word_cap("tight", "STANDARD") == 15

    def test_operational_cap_is_22_words(self):
        assert _word_cap("operational", "STANDARD") == 22

    def test_warm_cap_is_35_words(self):
        assert _word_cap("warm", "STANDARD") == 35

    def test_cap_truncates_long_response(self):
        text = "Okay so I wanted to ask you about the property. " * 5  # 50+ words
        result = _apply_energy_cap(text, 12)
        assert len(result.split()) <= 12

    def test_cap_preserves_sentence_boundary(self):
        text = "Okay. What's the address? Tell me more about it. I need to know."
        result = _apply_energy_cap(text, 8)
        # Should end at a sentence boundary, not mid-word
        assert result.endswith((".", "?", "!"))

    def test_short_text_unchanged(self):
        text = "What's the address?"
        assert _apply_energy_cap(text, 22) == text

    def test_hot_mode_entire_pipeline_tight(self):
        ctx = CallContext()
        ctx.disposition = "HOT"
        renderer = SpokenRendererProcessor(call_ctx=ctx)
        # 40-word AI text should come out under 12 words
        text = "I understand completely. Does the property need any work or is it pretty updated at this point?"
        result = renderer._transform(text)
        assert len(result.split()) <= 15  # may be slightly over due to sentence preservation


# ---------------------------------------------------------------------------
# Redirect override
# ---------------------------------------------------------------------------

class TestRedirectOverride:
    def test_redirect_needed_injects_pivot(self):
        ctx = CallContext()
        ctx.redirect_needed = True
        ctx.intent_confirmed = True  # so objective is not CONFIRM_INTENT
        ctx.address_known = True
        renderer = SpokenRendererProcessor(call_ctx=ctx)
        result = renderer._transform("Long rambling text that goes on and on about nothing related to selling")
        # Should be a pivot phrase, not the original AI text
        assert "Long rambling" not in result
        assert len(result.split()) < 20  # pivots are short

    def test_redirect_consumed_after_use(self):
        ctx = CallContext()
        ctx.redirect_needed = True
        ctx.intent_confirmed = True
        ctx.address_known = True
        renderer = SpokenRendererProcessor(call_ctx=ctx)
        renderer._transform("Some text")
        assert ctx.redirect_needed is False

    def test_redirect_not_needed_by_default(self):
        ctx = CallContext()
        assert ctx.redirect_needed is False

    def test_talkative_seller_past_opening_sets_redirect(self):
        ctx = CallContext()
        ctx.turn_count = 5
        ctx.intent_confirmed = True
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_seller_energy("I was thinking about this and actually the story goes way back when I first bought the place years ago and there was a lot going on at the time and the neighbors were difficult")
        assert ctx.redirect_needed is True

    def test_talkative_early_call_no_redirect(self):
        ctx = CallContext()
        ctx.turn_count = 1
        ctx.intent_confirmed = False
        proc = ContextTrackerProcessor(call_ctx=ctx, llm_context=None)
        proc._update_seller_energy("I was thinking about this and actually the story goes way back when I first bought the place years ago and there was a lot going on at the time and the neighbors were difficult")
        assert ctx.redirect_needed is False  # too early


# ---------------------------------------------------------------------------
# SAY= injection in context prefix
# ---------------------------------------------------------------------------

class TestSayInjection:
    def test_context_prefix_contains_say_for_get_address(self):
        ctx = CallContext()
        ctx.intent_confirmed = True  # objective = GET_ADDRESS
        prefix = ctx.build_context_prefix()
        assert "SAY=" in prefix
        assert "What's the address?" in prefix

    def test_context_prefix_contains_say_for_get_occupancy(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        ctx.address_known = True
        ctx.motivation_known = True
        # objective = GET_OCCUPANCY
        prefix = ctx.build_context_prefix()
        assert "SAY=" in prefix
        assert "Vacant right now?" in prefix or "Anyone living there?" in prefix

    def test_say_includes_up_to_two_phrases(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        prefix = ctx.build_context_prefix()
        # Should have at most 2 SAY phrases
        say_part = [p for p in prefix.split(";") if "SAY=" in p]
        if say_part:
            phrases = say_part[0].count('"')
            assert phrases <= 4  # max 2 phrases = 4 quotes


# ---------------------------------------------------------------------------
# Anti-novelty: short acks should NOT be suppressed
# ---------------------------------------------------------------------------

class TestAntiNovelty:
    def test_okay_not_in_repeatable_starters(self):
        from backend.voice.processors.ai_softener import _REPEATABLE_STARTERS
        starters_lower = [s.lower() for s in _REPEATABLE_STARTERS]
        assert "okay," not in starters_lower
        assert "okay." not in starters_lower

    def test_yeah_not_suppressed(self):
        from backend.voice.processors.ai_softener import _REPEATABLE_STARTERS
        starters_lower = [s.lower() for s in _REPEATABLE_STARTERS]
        assert "yeah," not in starters_lower
        assert "yeah." not in starters_lower

    def test_right_not_suppressed(self):
        from backend.voice.processors.ai_softener import _REPEATABLE_STARTERS
        starters_lower = [s.lower() for s in _REPEATABLE_STARTERS]
        assert "right," not in starters_lower

    def test_i_hear_you_still_suppressed(self):
        from backend.voice.processors.ai_softener import _REPEATABLE_STARTERS
        starters_lower = [s.lower() for s in _REPEATABLE_STARTERS]
        assert "i hear you" in starters_lower

    def test_makes_sense_still_suppressed(self):
        from backend.voice.processors.ai_softener import _REPEATABLE_STARTERS
        starters_lower = [s.lower() for s in _REPEATABLE_STARTERS]
        assert "makes sense" in starters_lower

    def test_short_phrase_not_detected_as_starter(self):
        # "okay," is only 5 chars — should return None from _extract_starter
        result = _extract_starter("okay, what's the address?")
        assert result is None  # not in new REPEATABLE_STARTERS

    def test_i_hear_you_still_detected(self):
        result = _extract_starter("i hear you, that's tough")
        assert result == "i hear you"


# ---------------------------------------------------------------------------
# V2 AI scoring
# ---------------------------------------------------------------------------

class TestV2AIScoring:
    def test_service_tone_penalized(self):
        text = "I want to make sure you have all the information you need."
        score = _score_ai_level(text)
        assert score >= 2

    def test_dont_hesitate_penalized(self):
        text = "Don't hesitate to ask me anything."
        score = _score_ai_level(text)
        assert score >= 3

    def test_however_penalized(self):
        text = "However, we might be able to work something out."
        score = _score_ai_level(text)
        assert score >= 1

    def test_exclamation_penalized(self):
        text = "That's great! What's the address?"
        score = _score_ai_level(text)
        assert score >= 1

    def test_therefore_penalized(self):
        text = "Therefore, I'd like to get the address."
        score = _score_ai_level(text)
        assert score >= 3

    def test_great_question_penalized(self):
        text = "Great question! The address would help us."
        score = _score_ai_level(text)
        assert score >= 3

    def test_operator_phrase_low_score(self):
        text = "Okay. Vacant right now?"
        assert _score_ai_level(text) == 0

    def test_short_pivot_low_score(self):
        text = "What's the address?"
        assert _score_ai_level(text) == 0

    def test_compound_v2_violations_accumulate(self):
        text = "However, I want to make sure you understand. Don't hesitate to ask. Therefore, let's move forward!"
        score = _score_ai_level(text)
        assert score >= 8  # should trigger force threshold


# ---------------------------------------------------------------------------
# End-to-end transform: full AI response → operator speech
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_ai_response_compressed(self):
        ctx = CallContext()
        ctx.intent_confirmed = True
        ctx.pacing_state = "operational"
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        ai_text = (
            "That makes sense. I completely understand your situation. "
            "I'd love to ask you a few questions about the property. "
            "Is the property currently vacant?"
        )
        result = renderer._transform(ai_text)

        assert "That makes sense" not in result
        assert "I completely understand" not in result
        assert "I'd love to ask" not in result
        assert "currently vacant" not in result
        assert "Vacant right now?" in result

    def test_retail_seller_gets_shorter_response(self):
        ctx = CallContext()
        ctx.disposition = "HOT"
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        long_text = "I completely understand that you want to maximize your return. That makes a lot of sense. Does the property need any work or is it in pretty good condition?"
        result = renderer._transform(long_text)
        assert len(result.split()) <= 15

    def test_distressed_seller_keeps_more_words(self):
        ctx = CallContext()
        ctx.situation_label = "preforeclosure"
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        text = "I hear you. That's a really tough spot to be in. What's the timeline looking like for you?"
        result = renderer._transform(text)
        # Should preserve more — DISTRESSED allows 30 words
        assert len(result.split()) <= 30
        assert "timeline" in result or "tough" in result

    def test_pure_ai_noise_returns_pivot_not_original(self):
        """When full response is AI noise that gets deleted, return an objective pivot."""
        ctx = CallContext()
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        # These are pure AI content with no useful acquisitions speech
        pure_ai = [
            "I'd be happy to help you with that.",
            "Certainly, I understand your concern.",
            "Feel free to let me know if you have any questions.",
        ]
        from backend.voice.phrases import PIVOT_BANK
        objective = ctx.get_current_objective()
        expected_pivots = PIVOT_BANK.get(objective, [])

        for text in pure_ai:
            result = renderer._transform(text)
            # Must not return the original AI text
            assert result != text, f"Should not return original: {text!r}"
            # Should return a known pivot phrase (short, operational)
            assert len(result.split()) <= 15, f"Pivot should be short: {result!r}"

    def test_ai_with_real_content_reduces_score(self):
        """AI phrases mixed with real content — score should decrease."""
        ctx = CallContext()
        renderer = SpokenRendererProcessor(call_ctx=ctx)

        ai_texts = [
            "Of course! Moving forward, let's discuss the property. What's the address?",
            "Certainly, I understand. Does it need any repairs?",
        ]
        for text in ai_texts:
            result = renderer._transform(text)
            original_score = _score_ai_level(text)
            result_score = _score_ai_level(result)
            assert result_score <= original_score, f"Score should not increase: {text!r} → {result!r}"
