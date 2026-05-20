from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_EMOTION_PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("GRIEVING", re.compile(
        r"\b(passed away|funeral|lost my|miss them|she died|he died|"
        r"my mother|my father|my husband|my wife|death|deceased)\b",
        re.IGNORECASE,
    ), 0.9),
    ("DISTRESSED", re.compile(
        r"\b(divorce|divorcing|foreclosure|behind on|auction|cancer|"
        r"sick|hospital|can't afford|desperate|losing the house|"
        r"eviction|bankrupt|debt|overwhelmed by)\b",
        re.IGNORECASE,
    ), 0.8),
    ("HOSTILE", re.compile(
        r"\b(stop calling|leave me alone|remove me|lawsuit|"
        r"not interested|never call again|do not call)\b",
        re.IGNORECASE,
    ), 0.95),
    ("OVERWHELMED", re.compile(
        r"\b(confused|too much|lot going on|I don't know|"
        r"complicated|overwhelmed|so much happening|hard to explain)\b",
        re.IGNORECASE,
    ), 0.6),
    ("SKEPTICAL", re.compile(
        r"\b(scam|too good|is this legit|prove it|how do I know|"
        r"not sure about|sounds fishy|who are you really)\b",
        re.IGNORECASE,
    ), 0.7),
    ("URGENT", re.compile(
        r"\b(asap|right away|immediately|need to move fast|"
        r"running out of time|deadline|very soon|no time)\b",
        re.IGNORECASE,
    ), 0.7),
    ("EXCITED", re.compile(
        r"\b(definitely|absolutely|let's do it|I'm ready|"
        r"sounds great|when can you|yes please|perfect)\b",
        re.IGNORECASE,
    ), 0.8),
    ("OPEN", re.compile(
        r"\b(tell me more|sounds good|okay|makes sense|"
        r"I'm listening|go ahead|sure|that's fair)\b",
        re.IGNORECASE,
    ), 0.4),
]

_NEUTRAL_THRESHOLD = 0.2
_INTENSITY_PER_MATCH = 0.3
_REPEAT_BONUS = 0.2
_BREVITY_PENALTY_THRESHOLD = 4


class EmotionalStateEngine(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._prev_emotion: str = "NEUTRAL"
        self._prev_intensity: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_emotional_state(text)

        await self.push_frame(frame, direction)

    def _update_emotional_state(self, text: str) -> None:
        detected_emotion = "NEUTRAL"
        detected_intensity = 0.0
        highest_base = 0.0

        for emotion, pattern, base_intensity in _EMOTION_PATTERNS:
            matches = pattern.findall(text)
            if not matches:
                continue

            intensity = min(1.0, base_intensity + (len(matches) - 1) * _INTENSITY_PER_MATCH)

            if emotion == self._prev_emotion:
                intensity = min(1.0, intensity + _REPEAT_BONUS)

            word_count = len(text.split())
            if word_count < _BREVITY_PENALTY_THRESHOLD:
                intensity = max(0.0, intensity - 0.15)

            if intensity > highest_base:
                highest_base = intensity
                detected_emotion = emotion
                detected_intensity = intensity

        if detected_intensity < _NEUTRAL_THRESHOLD:
            detected_emotion = "NEUTRAL"
            detected_intensity = 0.0

        if (
            detected_emotion != self._prev_emotion
            or abs(detected_intensity - self._prev_intensity) > 0.1
        ):
            logger.info(
                "emotional_state updated emotion={} intensity={:.2f} prev={}",
                detected_emotion,
                detected_intensity,
                self._prev_emotion,
            )

        self._prev_emotion = detected_emotion
        self._prev_intensity = detected_intensity
        self._ctx.emotional_state = detected_emotion
        self._ctx.emotional_intensity = detected_intensity