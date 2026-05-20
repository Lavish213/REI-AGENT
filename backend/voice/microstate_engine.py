from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_COMMITTING_PATTERNS = re.compile(
    r"\b(when can you come|let's do it|what's next|I'm ready|"
    r"sounds good|let's move forward|yes|when can we|"
    r"what would you offer|how soon can you close)\b",
    re.IGNORECASE,
)

_TESTING_PATTERNS = re.compile(
    r"\b(how do I know|prove it|what makes you different|"
    r"why should I|other buyers|is this legit|what company|"
    r"can you show me|send me something|what's your number)\b",
    re.IGNORECASE,
)

_VENTING_MIN_WORDS = 20

_SOFTENING_PATTERNS = re.compile(
    r"\b(maybe|possibly|could work|might consider|depends|"
    r"tell me more|what would you offer|how does it work|"
    r"I'm listening|go ahead|what's the process)\b",
    re.IGNORECASE,
)

_CLOSING_PATTERNS = re.compile(
    r"\b(thanks|goodbye|talk later|gotta go|I'll let you know|"
    r"appreciate it|bye|take care|talk soon)\b",
    re.IGNORECASE,
)

_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_HIGH_RESISTANCE = frozenset(["HIGH", "BLOCKING"])


class MicrostateEngine(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._prev_microstate: str = "NEUTRAL"
        self._duration_turns: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_microstate(text)

        await self.push_frame(frame, direction)

    def _update_microstate(self, text: str) -> None:
        emotional_state = getattr(self._ctx, "emotional_state", "NEUTRAL")
        resistance_level = getattr(self._ctx, "resistance_level", "NONE")
        resistance_softening = getattr(self._ctx, "resistance_softening", False)
        trust_score = getattr(self._ctx, "trust_score", 5.0)
        word_count = len(text.split())

        microstate = self._detect(
            text=text,
            emotional_state=emotional_state,
            resistance_level=resistance_level,
            resistance_softening=resistance_softening,
            trust_score=trust_score,
            word_count=word_count,
        )

        if microstate == self._prev_microstate:
            self._duration_turns += 1
        else:
            logger.info(
                "microstate changed from={} to={} duration_turns={}",
                self._prev_microstate,
                microstate,
                self._duration_turns,
            )
            self._prev_microstate = microstate
            self._duration_turns = 1

        self._ctx.microstate = microstate
        self._ctx.microstate_duration = self._duration_turns

    def _detect(
        self,
        text: str,
        emotional_state: str,
        resistance_level: str,
        resistance_softening: bool,
        trust_score: float,
        word_count: int,
    ) -> str:
        if _COMMITTING_PATTERNS.search(text):
            return "COMMITTING"

        if _CLOSING_PATTERNS.search(text):
            return "CLOSING"

        if _TESTING_PATTERNS.search(text) or trust_score < 3.5:
            return "TESTING"

        if resistance_softening and resistance_level in _HIGH_RESISTANCE:
            return "SOFTENING"

        if (
            emotional_state in _DISTRESSED_STATES
            and word_count >= _VENTING_MIN_WORDS
        ):
            return "VENTING"

        if resistance_level in _HIGH_RESISTANCE and not resistance_softening:
            return "VENTING"

        return "NEUTRAL"