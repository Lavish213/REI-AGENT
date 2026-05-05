import asyncio
import random

from loguru import logger

from pipecat.frames.frames import Frame, InterruptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


INTERRUPTION_ACKNOWLEDGMENTS = [
    "Oh— yeah go ahead",
    "Sorry— yeah?",
    "Mm— yeah?",
    "Oh— what's up?",
    "Go ahead—",
]


class InterruptionAckProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._last_ack: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            asyncio.create_task(self._queue_ack())

        await self.push_frame(frame, direction)

    async def _queue_ack(self):
        await asyncio.sleep(0.1)
        candidates = [a for a in INTERRUPTION_ACKNOWLEDGMENTS if a != self._last_ack]
        if not candidates:
            candidates = INTERRUPTION_ACKNOWLEDGMENTS
        ack = random.choice(candidates)
        self._last_ack = ack
        logger.debug("interruption ack={}", ack)
        await self.push_frame(TTSSpeakFrame(text=ack))
