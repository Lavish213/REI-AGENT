from __future__ import annotations

import re

from pipecat.frames.frames import (
    AggregationType,
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_BOUNDARY = re.compile(r"(?<!\d)[.!?](?=\s|$)|(?<=\d)[.!?](?=\s)")
_MAX_BUFFER = 1200


class SentenceStreamProcessor(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer = ""

    async def _flush(self, text: str, direction: FrameDirection) -> None:
        if text.strip():
            await self.push_frame(TTSTextFrame(text=text.strip() + " ", aggregated_by=AggregationType.SENTENCE), direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame, LLMFullResponseStartFrame)):
            self._buffer = ""
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMTextFrame):
            self._buffer += frame.text
            while match := _BOUNDARY.search(self._buffer):
                boundary = match.end()
                await self._flush(self._buffer[:boundary], direction)
                self._buffer = self._buffer[boundary:]
            while len(self._buffer) > _MAX_BUFFER:
                boundary = self._buffer.rfind(" ", 0, _MAX_BUFFER)
                boundary = boundary if boundary > 0 else _MAX_BUFFER
                await self._flush(self._buffer[:boundary], direction)
                self._buffer = self._buffer[boundary:]
            return
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMFullResponseEndFrame):
            await self._flush(self._buffer, direction)
            self._buffer = ""
        await self.push_frame(frame, direction)
