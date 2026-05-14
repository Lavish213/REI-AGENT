import re

from loguru import logger

from pipecat.frames.frames import AggregationType, Frame, LLMFullResponseEndFrame, LLMTextFrame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_HARD_BOUNDARY = re.compile(r"(?<=[.?!:])\s+|(?<=[.?!:])$|(?<=—)\s*|(?<=—)$")

_COMMA_MIN_WORDS = 5


def _word_count(text: str) -> int:
    return len(text.split())


def _find_hard_boundary(text: str) -> int:
    for m in _HARD_BOUNDARY.finditer(text):
        candidate = text[: m.start() + 1].rstrip()
        if _word_count(candidate) >= 5:
            return m.end()
    return -1


def _find_comma_boundary(text: str) -> int:
    idx = text.find(",")
    if idx == -1:
        return -1
    if _word_count(text[:idx]) >= _COMMA_MIN_WORDS:
        return idx + 1
    return -1


class SentenceStreamProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._buffer = ""

    async def _flush(self, text: str, direction: FrameDirection) -> None:
        text = text.strip()
        if text:
            logger.debug("sentence_streamer flush text={!r}", text)
            await self.push_frame(TTSTextFrame(text=text, aggregated_by=AggregationType.SENTENCE), direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            text = frame.text if hasattr(frame, "text") else ""
            self._buffer += text
            while True:
                boundary = _find_hard_boundary(self._buffer)
                if boundary != -1:
                    chunk = self._buffer[:boundary]
                    self._buffer = self._buffer[boundary:]
                    await self._flush(chunk, direction)
                    continue
                boundary = _find_comma_boundary(self._buffer)
                if boundary != -1:
                    chunk = self._buffer[:boundary]
                    self._buffer = self._buffer[boundary:]
                    await self._flush(chunk, direction)
                    continue
                break
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            remaining = self._buffer.strip()
            self._buffer = ""
            if remaining:
                await self._flush(remaining, direction)
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
