from __future__ import annotations

import asyncio
import random

from loguru import logger


_RECOVERY_PHRASES: dict[str, list[str]] = {
    "standard": ["You still there?", "Still with me?", "Hey — you there?"],
    "post_emotional": ["Take your time.", "No rush.", "Still here whenever you're ready."],
    "post_price": ["Still there?", "Did I lose you?"],
    "post_appointment": ["Did I lose you?", "You still there?"],
    "consecutive_2": ["Hey — still there?", "Hello?"],
}

_TIMEOUTS: dict[str, float] = {
    "standard": 4.0,
    "post_emotional": 8.0,
    "post_price": 7.0,
    "post_appointment": 8.0,
    "consecutive_2": 4.0,
}

_EMOTIONAL_MULTIPLIERS: dict[str, float] = {
    "DISTRESSED": 1.4,
    "GRIEVING": 1.5,
    "OVERWHELMED": 1.4,
    "HOSTILE": 0.6,
    "EXCITED": 0.8,
}

_CONSECUTIVE_SILENCE_END = 3
_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])


def _get_context(call_ctx) -> str:
    objective = getattr(call_ctx, "objective", "GET_MOTIVATION")
    emotional_state = getattr(call_ctx, "emotional_state", "NEUTRAL")
    consecutive = getattr(call_ctx, "consecutive_silences", 0)

    if consecutive >= 2:
        return "consecutive_2"
    if objective == "BOOK_APPOINTMENT":
        return "post_appointment"
    if getattr(call_ctx, "last_price_mentioned", None):
        return "post_price"
    if emotional_state in _DISTRESSED_STATES:
        return "post_emotional"
    return "standard"


def _get_timeout(context: str, call_ctx) -> float:
    base = _TIMEOUTS.get(context, 6.0)
    emotional_state = getattr(call_ctx, "emotional_state", "NEUTRAL")
    multiplier = _EMOTIONAL_MULTIPLIERS.get(emotional_state, 1.0)
    return base * multiplier


class SilenceHandler:
    def __init__(self, call_ctx, task):
        self._ctx = call_ctx
        self._task = task
        self._timer: asyncio.Task | None = None
        self._last_phrase: str | None = None
        self._consecutive_silences: int = 0

    def start_timer(self) -> None:
        self.cancel_timer()
        self._timer = asyncio.create_task(self._run_timer())

    def cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
            self._timer = None

    async def _run_timer(self) -> None:
        try:
            context = _get_context(self._ctx)
            timeout = _get_timeout(context, self._ctx)

            logger.debug("silence_handler timer started context={} timeout={:.1f}s", context, timeout)

            await asyncio.sleep(timeout)

            self._consecutive_silences += 1
            self._ctx.consecutive_silences = self._consecutive_silences

            if self._consecutive_silences >= _CONSECUTIVE_SILENCE_END:
                logger.info("silence_handler consecutive_limit reached count={} ending call", self._consecutive_silences)
                from pipecat.frames.frames import TTSSpeakFrame
                await self._task.queue_frames([TTSSpeakFrame(
                    "Hey — even if the timing's not right, "
                    "do you know anyone else around there thinking about selling?"
                )])
                await asyncio.sleep(4.0)
                self._ctx.call_should_end = True
                self._consecutive_silences = 0
                self._ctx.consecutive_silences = 0
                return

            phrase = self._pick_phrase(context)
            logger.info("silence_handler firing phrase={!r} context={} consecutive={}", phrase, context, self._consecutive_silences)

            from pipecat.frames.frames import TTSSpeakFrame
            await self._task.queue_frames([TTSSpeakFrame(phrase)])

        except asyncio.CancelledError:
            pass
        except Exception as error:
            logger.exception("silence_handler error error={}", str(error))

    def _pick_phrase(self, context: str) -> str:
        options = _RECOVERY_PHRASES.get(context, _RECOVERY_PHRASES["standard"])
        filtered = [p for p in options if p != self._last_phrase]
        phrase = random.choice(filtered or options)
        self._last_phrase = phrase
        return phrase

    def reset_consecutive(self) -> None:
        self._consecutive_silences = 0
        self._ctx.consecutive_silences = 0
