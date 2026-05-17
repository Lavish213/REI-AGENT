"""
Batch 4 regression tests — operator phrase routing + AI leak removal.

Tests retained for current implementation:
- Substitution engine: AI phrases → operator equivalents
- Anti-novelty: short acks no longer suppressed
"""
from __future__ import annotations

from backend.voice.processors.spoken_renderer import (
    SpokenRendererProcessor,
    _apply_substitutions,
)
from backend.voice.processors.ai_softener import _extract_starter
from backend.voice.processors.context_tracker import CallContext


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

    def test_is_property_vacant_compressed(self):
        result = _apply_substitutions("Is the property currently vacant?")
        assert result == "Vacant right now?"

    def test_are_you_living_there_compressed(self):
        result = _apply_substitutions("Are you currently living there?")
        assert result == "Living there now?"

    def test_could_you_provide_address_compressed(self):
        result = _apply_substitutions("Could you provide the full address?")
        assert result == "What's the address?"

    def test_does_it_need_work_compressed(self):
        result = _apply_substitutions("Does it need any repairs?")
        assert result == "Need much work?"

    def test_how_soon_looking_to_sell_compressed(self):
        result = _apply_substitutions("How soon are you looking to sell?")
        assert "How soon" in result

    def test_what_is_your_timeline_compressed(self):
        result = _apply_substitutions("What's your timeline for the sale?")
        assert "timeline look like" in result

    def test_clean_text_unchanged(self):
        text = "Okay. What's the address?"
        assert _apply_substitutions(text) == text

    def test_operator_speech_unchanged(self):
        text = "Vacant right now?"
        assert _apply_substitutions(text) == text


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
        result = _extract_starter("okay, what's the address?")
        assert result is None

    def test_i_hear_you_still_detected(self):
        result = _extract_starter("i hear you, that's tough")
        assert result == "i hear you"
