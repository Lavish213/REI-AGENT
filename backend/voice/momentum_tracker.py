from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_POSITIVE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(yeah|okay|right|sure|makes sense|sounds good)\b", re.IGNORECASE), 0.3),
    (re.compile(r"\b(tell me more|how does it work|what's the process)\b", re.IGNORECASE), 1.0),
    (re.compile(r"\b(when can you|what would you offer|how fast|let's do it)\b", re.IGNORECASE), 1.5),
    (re.compile(r"\b(I'm ready|definitely|absolutely|that works)\b", re.IGNORECASE), 1.2),
    (re.compile(r"\b(free and clear|no mortgage|vacant|need to sell fast)\b", re.IGNORECASE), 0.5),
]

_NEGATIVE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(not interested|stop calling|never mind|forget it)\b", re.IGNORECASE), 2.0),
    (re.compile(r"\b(think about it|need time|not ready|call me later)\b", re.IGNORECASE), 1.0),
    (re.compile(r"\b(too low|not enough|worth more)\b", re.IGNORECASE), 1.0),
    (re.compile(r"\b(I don't know|not sure|confused|complicated)\b", re.IGNORECASE), 0.5),
]

_SCORE_MIN = 0.0
_SCORE_MAX = 10.0
_START_SCORE = 5.0
_DIRECTION_THRESHOLD = 0.3
_SHORT_RESPONSE_PENALTY = 0.5
_SHORT_RESPONSE_WORDS = 4
_LONG_RESPONSE_BONUS = 0.5
_LONG_RESPONSE_WORDS = 12
_QUESTION_BONUS = 0.4
_DECAY_PER_NEUTRAL_TURN = 0.1


class MomentumTracker(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._score: float = _START_SCORE
        self._prev_score: float = _START_SCORE
        self._consecutive_positive: int = 0
        self._consecutive_negative: int = 0
        self._peak_score: float = _START_SCORE

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_momentum(text)

        await self.push_frame(frame, direction)

    def _update_momentum(self, text: str) -> None:
        delta = 0.0
        matched = False
        word_count = len(text.split())

        for pattern, amount in _POSITIVE_SIGNALS:
            if pattern.search(text):
                delta += amount
                matched = True

        for pattern, amount in _NEGATIVE_SIGNALS:
            if pattern.search(text):
                delta -= amount
                matched = True

        if word_count < _SHORT_RESPONSE_WORDS and not matched:
            delta -= _SHORT_RESPONSE_PENALTY

        if word_count > _LONG_RESPONSE_WORDS:
            delta += _LONG_RESPONSE_BONUS

        if "?" in text:
            delta += _QUESTION_BONUS

        if not matched and delta == 0.0:
            delta -= _DECAY_PER_NEUTRAL_TURN

        self._score = max(_SCORE_MIN, min(_SCORE_MAX, self._score + delta))

        if self._score > self._peak_score:
            self._peak_score = self._score

        if self._score > self._prev_score + _DIRECTION_THRESHOLD:
            direction = "RISING"
            self._consecutive_positive += 1
            self._consecutive_negative = 0
        elif self._score < self._prev_score - _DIRECTION_THRESHOLD:
            direction = "FALLING"
            self._consecutive_negative += 1
            self._consecutive_positive = 0
        else:
            direction = "STABLE"

        if abs(self._score - self._prev_score) > 0.2:
            logger.info(
                "momentum updated score={:.2f} direction={} "
                "pos_streak={} neg_streak={}",
                self._score,
                direction,
                self._consecutive_positive,
                self._consecutive_negative,
            )

        self._prev_score = self._score
        self._ctx.momentum_score = self._score
        self._ctx.momentum_direction = direction