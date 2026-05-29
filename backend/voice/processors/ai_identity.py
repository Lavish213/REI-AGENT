from __future__ import annotations

import re
from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_AI_QUESTION = re.compile(
    r"\b(are you a robot|are you ai|are you real|is this automated|are you human|are you a bot|are you a computer|is this a recording)\b",
    re.IGNORECASE,
)

_SB1001_DISCLOSURE = (
    "I'm Sophia — an automated assistant for San Joaquin House Buyers. "
    "Would you like to speak with someone directly?"
)


class AIIdentityProcessor(FrameProcessor):
    def __init__(self, call_ctx=None):
        super().__init__()
        self._ctx = call_ctx
        self._disclosed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if _AI_QUESTION.search(text) and not self._disclosed:
                self._disclosed = True
                logger.info("ai_identity SB1001 disclosure triggered")
                if self._ctx is not None:
                    self._ctx.runtime_instruction = (
                        f"[Seller asked if you are AI. Respond exactly: '{_SB1001_DISCLOSURE}']"
                    )

        await self.push_frame(frame, direction)
