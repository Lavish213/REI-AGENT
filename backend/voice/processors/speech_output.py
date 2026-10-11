from __future__ import annotations

import re

from pipecat.frames.frames import Frame, TextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_TAG = re.compile(r"\[[^\]]{1,80}\]|<[^>]{1,120}>")


class SpeechOutputProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, (TextFrame, TTSSpeakFrame)):
            frame.text = _TAG.sub("", frame.text)
            frame.text = re.sub(r"[*`#]", "", frame.text).strip()
            if not frame.text:
                return
        await self.push_frame(frame, direction)
