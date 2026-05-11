import re

from loguru import logger

from pipecat.frames.frames import AggregationType, Frame, LLMFullResponseEndFrame, LLMTextFrame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_BOUNDARY_PATTERN = re.compile(r"(?<=[.?!])\s+|(?<=[.?!])$")


def _word_count(text: str) -> int:
    return len(text.split())


def _find_sentence_boundary(text: str) -> int:
    for m in _BOUNDARY_PATTERN.finditer(text):
        candidate = text[: m.start() + 1].rstrip()
        if _word_count(candidate) >= 1:
            return m.end()
    return -1


class SentenceStreamProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._buffer = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            text = frame.text if hasattr(frame, "text") else ""
            self._buffer += text
            while True:
                boundary = _find_sentence_boundary(self._buffer)
                if boundary == -1:
                    break
                sentence = self._buffer[:boundary].rstrip()
                self._buffer = self._buffer[boundary:]
                logger.debug("sentence_streamer flushing sentence={!r}", sentence)
                await self.push_frame(TTSTextFrame(text=sentence, aggregated_by=AggregationType.SENTENCE), direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            remaining = self._buffer.strip()
            self._buffer = ""
            if remaining:
                if _word_count(remaining) >= 3:
                    logger.debug("sentence_streamer end-flush sentence={!r}", remaining)
                    await self.push_frame(TTSTextFrame(text=remaining, aggregated_by=AggregationType.SENTENCE), direction)
                else:
                    logger.debug("sentence_streamer end-flush short remainder={!r}", remaining)
                    await self.push_frame(TTSTextFrame(text=remaining, aggregated_by=AggregationType.SENTENCE), direction)
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

