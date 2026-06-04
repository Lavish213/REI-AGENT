import asyncio
import random

from loguru import logger

from pipecat.frames.frames import Frame, InterruptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


INTERRUPTION_ACKNOWLEDGMENTS = [
    "Yeah.",
    "Mm.",
    "Go ahead.",
    "Sure.",
    "Yep.",
]


class InterruptionAckProcessor(FrameProcessor):
    def __init__(self, call_ctx=None):
        super().__init__()
        self._last_ack: str | None = None
        self._ctx = call_ctx

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            opener_fired = getattr(self._ctx, "_opener_fired", True)
            if opener_fired:
                asyncio.create_task(self._queue_ack())

        await self.push_frame(frame, direction)

    async def _queue_ack(self):
        await asyncio.sleep(0.25)
        candidates = [a for a in INTERRUPTION_ACKNOWLEDGMENTS if a != self._last_ack]
        if not candidates:
            candidates = INTERRUPTION_ACKNOWLEDGMENTS
        ack = random.choice(candidates)
        self._last_ack = ack
        logger.debug("interruption ack={}", ack)
        await self.push_frame(TTSSpeakFrame(text=ack), FrameDirection.DOWNSTREAM)
