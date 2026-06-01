from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from pipecat.frames.frames import AggregationType, BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame
from pipecat.frames.frames import InterimTranscriptionFrame
from pipecat.frames.frames import LLMFullResponseEndFrame
from pipecat.frames.frames import TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frame_processor import FrameProcessor


_BACKCHANNELS = ["mmhm", "yeah", "right", "gotcha", "okay"]
_EMOTIONAL_BACKCHANNELS = ["yeah", "oh man", "mmhm"]
_SKEPTICAL_BACKCHANNELS = ["yeah", "right"]

_BLOCKING_PHRASES = ["hold on", "wait", "stop", "what do you mean", "i don't understand", "are you a robot", "are you ai"]
_EMOTIONAL_PHRASES = ["passed away", "divorce", "foreclosure", "behind on", "overwhelmed", "stress", "probate"]
_SKEPTICAL_PHRASES = ["scam", "legit", "not sure", "who are you"]

_SUPPRESS_EMOTIONAL_STATES = frozenset(["HOSTILE", "GRIEVING"])
_SUPPRESS_RESISTANCE_LEVELS = frozenset(["BLOCKING"])

_MIN_WORDS_BEFORE_BACKCHANNEL = 8
_MAX_BACKCHANNELS_PER_TURN = 2
_BACKCHANNEL_PROBABILITY = 0.20


@dataclass(slots=True)
class BackchannelState:
    seller_words_this_turn: int = 0
    backchannels_this_turn: int = 0
    last_backchannel: str | None = None

    def reset(self) -> None:
        self.seller_words_this_turn = 0
        self.backchannels_this_turn = 0
        self.last_backchannel = None


class BackchannelProcessor(FrameProcessor):
    def __init__(self, call_ctx: Any | None = None):
        super().__init__()
        self._state = BackchannelState()
        self._call_ctx = call_ctx
        self._bot_speaking: bool = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, InterimTranscriptionFrame):
            text = (frame.text or "").strip()
            if text and not self._bot_speaking:
                await self._maybe_backchannel(text=text, direction=direction)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            self._state.reset()
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def _maybe_backchannel(self, text: str, direction: FrameDirection) -> None:
        if self._call_ctx is not None:
            emotional_state = getattr(self._call_ctx, "emotional_state", "NEUTRAL")
            resistance_level = getattr(self._call_ctx, "resistance_level", "NONE")
            if emotional_state in _SUPPRESS_EMOTIONAL_STATES:
                return
            if resistance_level in _SUPPRESS_RESISTANCE_LEVELS:
                return

        words = re.findall(r"\b\w+\b", text)
        if not words:
            return

        self._state.seller_words_this_turn += len(words)

        if self._state.seller_words_this_turn < _MIN_WORDS_BEFORE_BACKCHANNEL:
            return
        if self._state.backchannels_this_turn >= _MAX_BACKCHANNELS_PER_TURN:
            return
        if not self._should_backchannel(text):
            return

        phrase = self._pick_backchannel(text)
        if not phrase:
            return

        self._state.backchannels_this_turn += 1
        self._state.last_backchannel = phrase
        self._state.seller_words_this_turn = 0

        logger.debug("backchannel emitted phrase={}", phrase)
        await self.push_frame(TTSTextFrame(text=phrase, aggregated_by=AggregationType.SENTENCE), direction)

    def _should_backchannel(self, text: str) -> bool:
        lower = text.lower()
        if "?" in text:
            return False
        if any(phrase in lower for phrase in _BLOCKING_PHRASES):
            return False
        if len(text.split()) < _MIN_WORDS_BEFORE_BACKCHANNEL:
            return False
        return random.random() < _BACKCHANNEL_PROBABILITY

    def _pick_backchannel(self, text: str) -> str:
        lower = text.lower()
        if any(phrase in lower for phrase in _EMOTIONAL_PHRASES):
            options = _EMOTIONAL_BACKCHANNELS
        elif any(phrase in lower for phrase in _SKEPTICAL_PHRASES):
            options = _SKEPTICAL_BACKCHANNELS
        else:
            options = _BACKCHANNELS
        filtered = [o for o in options if o != self._state.last_backchannel]
        return random.choice(filtered or options)
