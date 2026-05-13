"""
HumanizedLatencyProcessor — adds variable think delays before TTS to simulate
human response timing. Humans don't respond with uniform sub-100ms latency.

Wire BETWEEN sentence_streamer (or ai_softener) and tts.

Delay range is kept short (40–180ms) to stay within tolerable voice UX while
providing subconscious realism. Emotional turns get slightly longer delays.
"""
from __future__ import annotations

import asyncio
import random

from loguru import logger
from pipecat.frames.frames import Frame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# (min_ms, max_ms) per energy state — all kept under 200ms
_DELAY_BY_ENERGY: dict[str, tuple[int, int]] = {
    "calm":       (50, 140),
    "emotional":  (80, 180),   # pause — empathetic
    "skeptical":  (60, 150),   # slight deliberate pause
    "rushed":     (30, 80),    # snap back fast
    "talkative":  (40, 100),
    "hesitant":   (70, 160),   # thoughtful pause
    "motivated":  (35, 90),    # energetic reply
}

_DEFAULT_DELAY = (50, 130)


class HumanizedLatencyProcessor(FrameProcessor):
    """
    Injects a small random async sleep before each TTS text frame
    to simulate natural human response timing.
    """

    def __init__(self, energy_getter=None, **kwargs):
        super().__init__(**kwargs)
        # energy_getter: callable returning SellerEnergy string
        self._energy_getter = energy_getter
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if self._enabled and isinstance(frame, (TextFrame, TTSTextFrame)):
            energy = self._energy_getter() if self._energy_getter else "calm"
            min_ms, max_ms = _DELAY_BY_ENERGY.get(energy, _DEFAULT_DELAY)
            delay_ms = random.randint(min_ms, max_ms)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
                logger.debug("humanized_latency delay={}ms energy={}", delay_ms, energy)

        await self.push_frame(frame, direction)
