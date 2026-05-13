"""
SilenceDetectorProcessor — detects when seller stops responding after bot finishes
speaking and injects a soft re-engagement into the conversation.

Wire BEFORE context_aggregator.user() in the pipeline (after STT processors).

Recovery callback is injected AFTER task creation in agent.py:
    silence_detector.set_recovery_callback(async_cb)
"""
from __future__ import annotations

import asyncio
from typing import Callable, Coroutine

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Seconds of silence after bot finishes before recovery fires
_SILENCE_TIMEOUT = 9.0

# Recovery utterances — rotate so they don't repeat
_RECOVERY_PHRASES = [
    "Still there?",
    "No worries, take your time.",
    "I'm here whenever you're ready.",
    "You still with me?",
    "I know this is a lot to think about.",
]


class SilenceDetectorProcessor(FrameProcessor):
    """
    Monitors bot speech lifecycle. When bot finishes speaking and seller does not
    respond within SILENCE_TIMEOUT seconds, calls the recovery callback to inject
    a re-engagement utterance into the conversation.
    """

    def __init__(self, silence_timeout: float = _SILENCE_TIMEOUT, **kwargs):
        super().__init__(**kwargs)
        self._silence_timeout = silence_timeout
        self._bot_speaking = False
        self._timer_task: asyncio.Task | None = None
        self._recovery_cb: Callable[[str], Coroutine] | None = None
        self._phrase_idx = 0
        self._enabled = True

    def set_recovery_callback(self, cb: Callable[[str], Coroutine]) -> None:
        self._recovery_cb = cb
        logger.debug("silence_detector recovery callback registered")

    def disable(self) -> None:
        """Disable recovery (e.g. during wrap-up)."""
        self._enabled = False
        self._cancel_timer()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._cancel_timer()

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            if self._enabled:
                self._start_timer()

        elif isinstance(frame, UserStartedSpeakingFrame):
            self._cancel_timer()

        await self.push_frame(frame, direction)

    def _start_timer(self) -> None:
        self._cancel_timer()
        self._timer_task = asyncio.create_task(self._silence_timeout_handler())

    def _cancel_timer(self) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

    async def _silence_timeout_handler(self) -> None:
        try:
            await asyncio.sleep(self._silence_timeout)
            if not self._recovery_cb:
                logger.debug("silence_detector fired but no recovery callback set")
                return

            phrase = _RECOVERY_PHRASES[self._phrase_idx % len(_RECOVERY_PHRASES)]
            self._phrase_idx += 1
            logger.info("silence_detector firing recovery phrase={}", phrase)
            await self._recovery_cb(phrase)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("silence_detector recovery error={}", str(e))
