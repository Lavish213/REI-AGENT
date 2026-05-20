from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_STRIP_ALWAYS: list[re.Pattern] = [
    re.compile(r"^So basically[,.]?\s*", re.IGNORECASE),
    re.compile(r"^What that means is[,.]?\s*", re.IGNORECASE),
    re.compile(r"^Just to clarify[,.]?\s*", re.IGNORECASE),
    re.compile(r"^To summarize[,.]?\s*", re.IGNORECASE),
    re.compile(r"^In other words[,.]?\s*", re.IGNORECASE),
    re.compile(r"^What I mean is[,.]?\s*", re.IGNORECASE),
    re.compile(r"^Let me explain[,.]?\s*", re.IGNORECASE),
    re.compile(r"^Essentially[,.]?\s*", re.IGNORECASE),
    re.compile(r"Does that make sense\??\s*$", re.IGNORECASE),
    re.compile(r"Is that helpful\??\s*$", re.IGNORECASE),
    re.compile(r"Feel free to ask[^.]*\.\s*$", re.IGNORECASE),
    re.compile(r"Is there anything else[^.]*\?\s*$", re.IGNORECASE),
    re.compile(r"Let me know if you have[^.]*\.\s*$", re.IGNORECASE),
    re.compile(r"Don't hesitate to[^.]*\.\s*$", re.IGNORECASE),
    re.compile(r"I understand (that |your )[^.]*\.\s*", re.IGNORECASE),
    re.compile(r"I completely understand[^.]*\.\s*", re.IGNORECASE),
    re.compile(r"That('s| is) (totally |completely |absolutely )?understandable[^.]*\.\s*", re.IGNORECASE),
]

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

_MODE_LIMITS: dict[str, int] = {
    "HOT": 2,
    "FAST": 2,
    "DISTRESSED": 3,
    "GRIEVING": 2,
    "SKEPTICAL": 2,
    "INHERITED": 3,
    "LANDLORD": 2,
    "EMOTIONAL": 2,
    "STANDARD": 4,
    "RECOVERY": 2,
}

_EMOTIONAL_STATES_NO_SALES = frozenset(["GRIEVING", "DISTRESSED", "OVERWHELMED"])

_SALES_FORWARD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(this is a great opportunity|we can close fast|cash offer|as-is|no repairs needed)\b", re.IGNORECASE),
    re.compile(r"\b(you won't find a better|best option|smart move|take advantage)\b", re.IGNORECASE),
]

_RHYTHM_LONG_THRESHOLD = 20
_RHYTHM_SHORT_THRESHOLD = 8


def _strip_opener_phrases(text: str) -> str:
    for pattern in _STRIP_ALWAYS:
        text = pattern.sub("", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _enforce_length(sentences: list[str], mode: str) -> list[str]:
    limit = _MODE_LIMITS.get(mode, 3)
    return sentences[:limit]


def _remove_sales_language(sentences: list[str]) -> list[str]:
    cleaned = []
    for sentence in sentences:
        if any(p.search(sentence) for p in _SALES_FORWARD_PATTERNS):
            logger.debug("response_compressor stripped sales language sentence={!r}", sentence)
            continue
        cleaned.append(sentence)
    return cleaned if cleaned else sentences[:1]


def _apply_rhythm_bias(
    sentences: list[str],
    last_sophia_words: int,
    mode: str,
) -> list[str]:
    limit = _MODE_LIMITS.get(mode, 3)

    if last_sophia_words > _RHYTHM_LONG_THRESHOLD:
        limit = max(1, limit - 1)
    elif last_sophia_words < _RHYTHM_SHORT_THRESHOLD and last_sophia_words > 0:
        limit = min(limit + 1, _MODE_LIMITS.get("STANDARD", 4))

    return sentences[:limit]


class ResponseCompressor(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._buffer: list[str] = []
        self._collecting = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            if frame.text:
                self._buffer.append(frame.text)
                self._collecting = True
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            if self._collecting and self._buffer:
                raw = "".join(self._buffer).strip()
                compressed = self._compress(raw)

                word_count = len(compressed.split())
                self._ctx.last_sophia_words = word_count if hasattr(self._ctx, "last_sophia_words") else word_count

                logger.info(
                    "response_compressor original_words={} compressed_words={} mode={}",
                    len(raw.split()),
                    word_count,
                    self._ctx.get_seller_mode(),
                )

                await self.push_frame(TextFrame(text=compressed), direction)

            self._buffer = []
            self._collecting = False
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    def _compress(self, text: str) -> str:
        mode = self._ctx.get_seller_mode()
        emotional_state = getattr(self._ctx, "emotional_state", "NEUTRAL")
        last_sophia_words = getattr(self._ctx, "last_sophia_words", 0)

        text = _strip_opener_phrases(text)
        sentences = _split_sentences(text)

        if not sentences:
            return text

        if emotional_state in _EMOTIONAL_STATES_NO_SALES:
            sentences = _remove_sales_language(sentences)

        sentences = _enforce_length(sentences, mode)
        sentences = _apply_rhythm_bias(sentences, last_sophia_words, mode)

        return " ".join(sentences)