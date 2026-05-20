from __future__ import annotations

from collections import deque

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_LEVEL_THRESHOLDS = {
    "CRITICAL": 3,
    "HIGH": 6,
    "MODERATE": 10,
    "MILD": 15,
}

_CONSECUTIVE_SHORT_LIMIT = 3
_SHORT_WORD_THRESHOLD = 4
_HISTORY_SIZE = 5


def _words_to_level(avg: float, consecutive_short: int) -> str:
    if consecutive_short >= _CONSECUTIVE_SHORT_LIMIT:
        return "CRITICAL"
    if avg < _LEVEL_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if avg < _LEVEL_THRESHOLDS["HIGH"]:
        return "HIGH"
    if avg < _LEVEL_THRESHOLDS["MODERATE"]:
        return "MODERATE"
    if avg < _LEVEL_THRESHOLDS["MILD"]:
        return "MILD"
    return "FRESH"


class FatigueDetector(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._history: deque[int] = deque(maxlen=_HISTORY_SIZE)
        self._consecutive_short: int = 0
        self._prev_level: str = "FRESH"

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_fatigue(text)

        await self.push_frame(frame, direction)

    def _update_fatigue(self, text: str) -> None:
        word_count = len(text.split())
        self._history.append(word_count)

        if word_count <= _SHORT_WORD_THRESHOLD:
            self._consecutive_short += 1
        else:
            self._consecutive_short = 0

        avg = sum(self._history) / len(self._history)
        level = _words_to_level(avg, self._consecutive_short)

        if level != self._prev_level:
            logger.info(
                "fatigue_level changed from={} to={} avg_words={:.1f} consecutive_short={}",
                self._prev_level,
                level,
                avg,
                self._consecutive_short,
            )

        self._prev_level = level
        self._ctx.fatigue_level = level