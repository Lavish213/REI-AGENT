"""
Batch 3 regression tests — conversational realism + operator instinct.

Tests retained for current implementation:
- SpokenRenderer substitution: AI-complete → fragment speech
- SpokenRenderer AI setup stripping
- SpokenRenderer end-to-end transform
"""
from __future__ import annotations

import pytest

from backend.voice.processors.spoken_renderer import (
    SpokenRendererProcessor,
    _apply_substitutions as _apply_fragments,
    _strip_ai_setups,
)
from backend.voice.processors.context_tracker import CallContext


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
        text = "To better help you, are you living there now?"
        result = _strip_ai_setups(text)
        assert "To better help" not in result

    def test_no_setup_text_unchanged(self):
        text = "What's the address on that?"
        assert _strip_ai_setups(text) == text


# ---------------------------------------------------------------------------
# SpokenRenderer — end-to-end transform
# ---------------------------------------------------------------------------

class TestSpokenRendererTransform:
    def _renderer(self, **kwargs) -> SpokenRendererProcessor:
        ctx = CallContext()
        for k, v in kwargs.items():
            setattr(ctx, k, v)
        return SpokenRendererProcessor(call_ctx=ctx)

    def test_transform_compresses_fragment(self):
        renderer = self._renderer()
        result = renderer._transform("Is the property currently vacant?")
        assert "Vacant right now?" in result

    def test_transform_strips_setup(self):
        renderer = self._renderer()
        result = renderer._transform(
            "I'd love to ask you a few questions. What's the address?"
        )
        assert "I'd love to ask" not in result

    def test_transform_never_returns_empty(self):
        renderer = self._renderer()
        result = renderer._transform("   ")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_transform_returns_string(self):
        renderer = self._renderer()
        result = renderer._transform("Okay. What's the address?")
        assert isinstance(result, str)
