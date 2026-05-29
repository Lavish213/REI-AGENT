from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import AggregationType, Frame, LLMFullResponseEndFrame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_JARGON = [
    (re.compile(r'\bARV\b'), "what it'd be worth after repairs"),
    (re.compile(r'\bfix and flip\b', re.IGNORECASE), "fix it up and sell it"),
    (re.compile(r'\bwholesale\b', re.IGNORECASE), "work with a network of buyers"),
    (re.compile(r'\bMAO\b'), "what we can offer"),
    (re.compile(r'\bacquisitions\b', re.IGNORECASE), "buying"),
    (re.compile(r'\bunder contract\b', re.IGNORECASE), "in the process"),
    (re.compile(r'\bclose of escrow\b', re.IGNORECASE), "closing day"),
]

_XML_TAG = re.compile(r'<[a-z_/][^>]{0,60}>', re.IGNORECASE)
_MARKDOWN = re.compile(r'^#{1,3}\s+|[*`_]|^---+$', re.MULTILINE)
_BRACKET = re.compile(r'\[[A-Z][A-Z_ ]{0,40}\]')

_ACK_WORDS = frozenset([
    "got it", "okay", "alright", "right",
    "yeah", "sure", "understood", "okay so", "alright so",
])

_SPLIT_ON_ACK = re.compile(
    r'(?<!\w)(got it|okay so|alright so|okay|alright|right|yeah|sure|understood)[\s,—–-]+',
    re.IGNORECASE,
)

_SPLIT_ON_EMDASH = re.compile(r'\s*[—–]\s*')
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')
_TRAILING_CONJUNCTION = re.compile(
    r'\b(and|but|because|so|like|I mean|you know|well|actually|the thing is)\s*$',
    re.IGNORECASE,
)

_CHUNK_LIMITS: dict[str, int] = {
    "GRIEVING": 6,
    "DISTRESSED": 8,
    "OVERWHELMED": 7,
    "SKEPTICAL": 10,
    "HOSTILE": 8,
    "URGENT": 10,
    "EXCITED": 12,
    "OPEN": 14,
    "NEUTRAL": 15,
}

_DEFAULT_CHUNK_LIMIT = 15


def _transform(text: str) -> str:
    text = _XML_TAG.sub('', text)
    text = _MARKDOWN.sub('', text)
    text = _BRACKET.sub('', text)
    for pattern, replacement in _JARGON:
        text = pattern.sub(replacement, text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _get_chunk_limit(emotional_state: str) -> int:
    return _CHUNK_LIMITS.get(emotional_state, _DEFAULT_CHUNK_LIMIT)


def _split_on_ack(text: str) -> list[str]:
    parts = _SPLIT_ON_ACK.split(text)
    result: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        if not part:
            i += 1
            continue
        if part.lower() in {a.lower() for a in _ACK_WORDS}:
            if i + 1 < len(parts):
                next_part = parts[i + 1].strip()
                result.append(part + ".")
                if next_part:
                    result.append(next_part)
                i += 2
            else:
                result.append(part + ".")
                i += 1
        else:
            result.append(part)
            i += 1
    return [r for r in result if r.strip()]


def _split_into_chunks(text: str, word_limit: int) -> list[str]:
    emdash_parts = _SPLIT_ON_EMDASH.split(text)
    mid_chunks: list[str] = []

    for part in emdash_parts:
        part = part.strip()
        if not part:
            continue
        ack_parts = _split_on_ack(part)
        mid_chunks.extend(ack_parts)

    final_chunks: list[str] = []
    for chunk in mid_chunks:
        sentences = _SENTENCE_BOUNDARY.split(chunk.strip())
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            words = sentence.split()
            if len(words) <= word_limit:
                final_chunks.append(sentence)
            else:
                current: list[str] = []
                for word in words:
                    current.append(word)
                    if len(current) >= word_limit:
                        segment = " ".join(current).strip()
                        if not _TRAILING_CONJUNCTION.search(segment):
                            final_chunks.append(segment)
                            current = []
                if current:
                    final_chunks.append(" ".join(current).strip())

    return [c for c in final_chunks if c.strip()]


class SpeechChunker(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._buffer: list[str] = []
        self._collecting = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (TextFrame, TTSTextFrame)) and direction == FrameDirection.DOWNSTREAM:
            text = frame.text if hasattr(frame, "text") else ""
            if text:
                self._buffer.append(text)
                self._collecting = True
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            if self._collecting and self._buffer:
                raw = "".join(self._buffer).strip()
                full_text = _transform(raw)

                if not full_text:
                    self._buffer = []
                    self._collecting = False
                    await self.push_frame(frame, direction)
                    return

                emotional_state = getattr(self._ctx, "emotional_state", "NEUTRAL")
                word_limit = _get_chunk_limit(emotional_state)
                chunks = _split_into_chunks(full_text, word_limit)

                logger.info(
                    "speech_chunker chunks={} emotional_state={} word_limit={}",
                    len(chunks), emotional_state, word_limit,
                )

                for chunk in chunks:
                    await self.push_frame(
                        TTSTextFrame(text=chunk, aggregated_by=AggregationType.SENTENCE),
                        direction,
                    )

            self._buffer = []
            self._collecting = False
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
