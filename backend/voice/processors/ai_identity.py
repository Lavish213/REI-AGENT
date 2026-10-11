from __future__ import annotations

import re
from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_AI_QUESTION = re.compile(
    r"\b(eres (?:una? )?(?:ia|robot|bot)|estoy hablando con (?:una? )?persona real|is this artificial intelligence|are you automated|are you (?:a )?robot|are you (?:an? )?ai|are you real|is this automated|is this (?:a )?bot|am i talking to (?:a )?computer|(?:are you a )?real person|are you human|are you a bot|are you a computer|is this a recording)\b",
    re.IGNORECASE,
)

_SB1001_DISCLOSURE = (
    "I'm Sophia — an automated assistant for San Joaquin House Buyers. "
    "I can try connecting you with the team if you prefer."
)


class AIIdentityProcessor(FrameProcessor):
    def __init__(self, call_ctx=None):
        super().__init__(enable_direct_mode=True)
        self._ctx = call_ctx
        self._disclosed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if _AI_QUESTION.search(text):
                self._disclosed = True
                logger.info("ai_identity SB1001 disclosure triggered")
                if self._ctx is not None:
                    self._ctx.runtime_instruction = (
                        f"[Seller asked if you are AI. Respond exactly: '{_SB1001_DISCLOSURE}']"
                    )

        await self.push_frame(frame, direction)
