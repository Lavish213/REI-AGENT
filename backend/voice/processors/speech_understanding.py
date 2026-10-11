from __future__ import annotations

import math
import re

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def transcript_confidence(result) -> tuple[float | None, float | None, bool]:
    channel = _field(result, "channel")
    alternatives = _field(channel, "alternatives", []) or []
    if not alternatives:
        return None, None, False
    alternative = alternatives[0]
    values = [_field(alternative, "confidence")]
    words = [_field(word, "confidence") for word in (_field(alternative, "words", []) or [])]
    invalid = any(value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1) for value in values + words)
    overall = values[0] if not invalid else None
    valid_words = [value for value in words if value is not None] if not invalid else []
    return overall, min(valid_words) if valid_words else None, invalid


class SpeechUnderstandingProcessor(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__(enable_direct_mode=True)
        self._ctx = call_ctx

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame) and frame.text.strip():
            overall, weakest_word, invalid = transcript_confidence(frame.result)
            unclear_marker = bool(re.fullmatch(r"\s*[\[(]?(?:inaudible|unintelligible|crosstalk|static|noise)[\])]?\s*", frame.text, re.I))
            self._ctx.transcript_confidence = overall
            self._ctx.transcript_uncertain = invalid or unclear_marker or (overall is not None and overall < 0.55) or (weakest_word is not None and weakest_word < 0.35)
            if self._ctx.transcript_uncertain:
                self._ctx.clarification_failures += 1
            elif not re.search(r"hear|hearing|understand|repeat|muffled|breaking up|louder|pardon|huh", frame.text, re.I):
                self._ctx.clarification_failures = 0
        await self.push_frame(frame, direction)
