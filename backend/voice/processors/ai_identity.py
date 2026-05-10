import re
from loguru import logger
from pipecat.frames.frames import AggregationType, Frame, TranscriptionFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_IDENTITY_PATTERNS = re.compile(
    r"\b(are you (a |an )?(robot|bot|ai|computer|machine|automated|human|real|person)|"
    r"is this (a |an )?(bot|robot|ai|automated|computer)|"
    r"real person|talking to a (bot|robot|computer|machine)|"
    r"am i talking to)\b",
    re.IGNORECASE,
)

_DISCLOSURE = (
    "I'm Sophia — an automated assistant for San Joaquin House Buyers. "
    "Would you like to speak with someone directly?"
)


class AIIdentityProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._disclosed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if (
            not self._disclosed
            and isinstance(frame, TranscriptionFrame)
            and frame.text
            and _IDENTITY_PATTERNS.search(frame.text)
        ):
            self._disclosed = True
            logger.info("ai_identity_question detected — forcing disclosure")
            await self.push_frame(TTSTextFrame(text=_DISCLOSURE, aggregated_by=AggregationType.SENTENCE), direction)
            return

        await self.push_frame(frame, direction)
