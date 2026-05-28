from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_VAGUE_ANSWER = re.compile(
    r"^(uh|um|hmm|yeah|no|okay|sure|fine|maybe|"
    r"I guess|I don't know|not sure|kind of|sort of)\s*[.?!]?\s*$",
    re.IGNORECASE,
)

_BACKCHANNEL_ONLY = re.compile(
    r"^(mhm|mm+|uh huh|uhh?|hmm+)\s*[.?!]?\s*$",
    re.IGNORECASE,
)

_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_VENTING_MICROSTATE = frozenset(["VENTING"])

_DO_NOTHING_PHRASE = "Mmhm."
_VAGUE_RUNTIME_INSTRUCTION = (
    "[Seller answer was vague. Rephrase the same question "
    "differently before moving to next objective. "
    "Do not accept the vague answer and move on.]"
)


class TurnController(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._last_question_objective: str = ""
        self._vague_count: int = 0
        self._holding: bool = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                should_hold = await self._evaluate_turn(text)
                if should_hold:
                    return

        await self.push_frame(frame, direction)

    async def _evaluate_turn(self, text: str) -> bool:
        emotional_state = getattr(self._ctx, "emotional_state", "NEUTRAL")
        microstate = getattr(self._ctx, "microstate", "NEUTRAL")
        objective = getattr(self._ctx, "objective", "GET_MOTIVATION")
        word_count = len(text.split())

        if _BACKCHANNEL_ONLY.match(text):
            logger.debug("turn_controller backchannel suppressed text={!r}", text)
            return True

        if (
            emotional_state in _DISTRESSED_STATES
            and microstate in _VENTING_MICROSTATE
            and word_count > 15
        ):
            logger.debug("turn_controller emotional hold emotional_state={}", emotional_state)
            await self.push_frame(TTSSpeakFrame(_DO_NOTHING_PHRASE), FrameDirection.DOWNSTREAM)
            return True

        if _VAGUE_ANSWER.match(text) and word_count <= 4:
            self._vague_count += 1
            if self._vague_count <= 2:
                logger.info(
                    "turn_controller vague_answer detected count={} objective={}",
                    self._vague_count,
                    objective,
                )
                self._ctx.runtime_instruction = _VAGUE_RUNTIME_INSTRUCTION
            else:
                self._vague_count = 0
        else:
            self._vague_count = 0

        return False
