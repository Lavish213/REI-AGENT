from backend.voice.processors.ai_softener import _extract_starter


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
