from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_HARD_NO: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(not interested|stop calling|never selling|take me off)\b", re.IGNORECASE), "rejection"),
    (re.compile(r"\b(already listed|with an agent|on the mls)\b", re.IGNORECASE), "agent"),
    (re.compile(r"\b(keeping it|not selling|my kids will inherit)\b", re.IGNORECASE), "absolute"),
]

_SOFT_NO: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(think about it|need time|not sure yet|maybe later)\b", re.IGNORECASE), "hesitation"),
    (re.compile(r"\b(call me later|not right now|try me next)\b", re.IGNORECASE), "delay"),
    (re.compile(r"\b(talk to my spouse|check with family|ask my partner)\b", re.IGNORECASE), "delegation"),
    (re.compile(r"\b(send me something|email me|text me info)\b", re.IGNORECASE), "avoidance"),
    (re.compile(r"\b(too low|worth more|not accepting that|need more)\b", re.IGNORECASE), "price"),
]

_SOFTENING: re.Pattern = re.compile(
    r"\b(maybe|possibly|could work|might consider|depends|"
    r"tell me more|what would you offer|how does it work|"
    r"how fast|what's the process|I'm listening)\b",
    re.IGNORECASE,
)

_LEVEL_ORDER = ["NONE", "LOW", "MODERATE", "HIGH", "BLOCKING"]

_HARD_NO_SCORE = 3.0
_SOFT_NO_SCORE = 1.5
_SOFTENING_REDUCTION = 1.5
_SCORE_DECAY_PER_TURN = 0.2


def _score_to_level(score: float) -> str:
    if score >= 8.5:
        return "BLOCKING"
    if score >= 6.5:
        return "HIGH"
    if score >= 4.0:
        return "MODERATE"
    if score >= 2.0:
        return "LOW"
    return "NONE"


def _downgrade_level(level: str) -> str:
    idx = _LEVEL_ORDER.index(level) if level in _LEVEL_ORDER else 0
    return _LEVEL_ORDER[max(0, idx - 1)]


class ResistanceTracker(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._score: float = 0.0
        self._objection_types: list[str] = []
        self._prev_level: str = "NONE"
        self._turns_since_objection: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_resistance(text)

        await self.push_frame(frame, direction)

    def _update_resistance(self, text: str) -> None:
        matched_this_turn = False
        softening_detected = False

        for pattern, obj_type in _HARD_NO:
            if pattern.search(text):
                self._score = min(10.0, self._score + _HARD_NO_SCORE)
                if obj_type not in self._objection_types:
                    self._objection_types.append(obj_type)
                matched_this_turn = True
                self._turns_since_objection = 0
                logger.info("hard_no detected type={} score={:.1f}", obj_type, self._score)

        for pattern, obj_type in _SOFT_NO:
            if pattern.search(text):
                self._score = min(10.0, self._score + _SOFT_NO_SCORE)
                if obj_type not in self._objection_types:
                    self._objection_types.append(obj_type)
                matched_this_turn = True
                self._turns_since_objection = 0
                logger.info("soft_no detected type={} score={:.1f}", obj_type, self._score)

        if _SOFTENING.search(text) and self._score > 0:
            softening_detected = True
            self._score = max(0.0, self._score - _SOFTENING_REDUCTION)
            logger.info("resistance_softening detected score={:.1f}", self._score)

        if not matched_this_turn:
            self._turns_since_objection += 1
            self._score = max(0.0, self._score - _SCORE_DECAY_PER_TURN)

        level = _score_to_level(self._score)

        if level != self._prev_level:
            logger.info(
                "resistance_level changed from={} to={} score={:.1f}",
                self._prev_level,
                level,
                self._score,
            )

        self._prev_level = level
        self._ctx.resistance_level = level
        self._ctx.resistance_softening = softening_detected

        if "price" in self._objection_types:
            self._ctx.price_resistance = True if hasattr(self._ctx, "price_resistance") else None
        if "agent" in self._objection_types:
            self._ctx.has_agent = True