from __future__ import annotations

import asyncio
import re
import time

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_TRAILING_CONJUNCTION = re.compile(
    r"\b(and|but|because|so|like|I mean|you know|"
    r"well|actually|the thing is|anyway|plus)\s*$",
    re.IGNORECASE,
)

_VAGUE_ANSWER = re.compile(
    r"^(uh|um|hmm|yeah|no|okay|sure|fine|maybe|"
    r"I guess|I don't know|not sure|kind of|sort of)\s*[.?!]?\s*$",
    re.IGNORECASE,
)

_BACKCHANNEL_ONLY = re.compile(
    r"^(yeah|yep|right|okay|ok|mhm|mm|uh huh|sure|got it|"
    r"I see|I know|makes sense|totally|exactly)\s*[.?!]?\s*$",
    re.IGNORECASE,
)

_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_VENTING_MICROSTATE = frozenset(["VENTING"])

_SILENCE_WINDOWS: dict[str, float] = {
    "GET_MOTIVATION": 1.8,
    "EMOTIONAL_HOLD": 1.5,
    "GET_PRICE_ANCHOR": 1.0,
    "TRUST_REPAIR": 1.2,
    "HANDLE_OBJECTION": 0.8,
    "GET_TIMELINE": 0.6,
    "GET_CONDITION": 0.5,
    "GET_MORTGAGE": 0.5,
    "BOOK_APPOINTMENT": 0.4,
    "default": 0.4,
}

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

        if _TRAILING_CONJUNCTION.search(text):
            logger.debug("turn_controller trailing conjunction hold text={!r}", text)
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

        await self._apply_silence_window(objective)
        return False

    async def _apply_silence_window(self, objective: str) -> None:
        window = _SILENCE_WINDOWS.get(objective, _SILENCE_WINDOWS["default"])

        if window <= 0.1:
            return

        logger.debug(
            "turn_controller silence_window={:.2f}s objective={}",
            window,
            objective,
        )

        await asyncio.sleep(window)