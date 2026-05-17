from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from pipecat.frames.frames import (
    AggregationType,
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TextFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
)

if TYPE_CHECKING:
    from backend.voice.processors.context_tracker import (
        CallContext,
    )


_LEAKAGE_SAFE = (
    "Hey, this is Sophia with "
    "San Joaquin House Buyers."
)

_META_SAFE = (
    "Sorry about that — Sophia with "
    "San Joaquin House Buyers."
)



_LEAKAGE_PATTERNS = [
    re.compile(r"\[name\]", re.I),
    re.compile(r"\[address\]", re.I),
    re.compile(r"\binbound or outbound\b", re.I),
    re.compile(r"\bcall type\b", re.I),
    re.compile(r"\bright opening\b", re.I),
    re.compile(r"owner.{0,5}s name and address", re.I),
    re.compile(r"\bOUTBOUND\b"),
    re.compile(r"\bINBOUND\b"),
]

_MARKDOWN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*(.*?)\*\*"), r"\1"),
    (re.compile(r"__(.*?)__"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"^\s*[-*]\s+", re.MULTILINE), ""),
]

_META_BLOCK_PATTERNS = [
    re.compile(r"\bi haven'?t said anything yet\b", re.I),
    re.compile(r"\bthis is the start of (?:our|the) conversation\b", re.I),
    re.compile(r"\bthis conversation\b", re.I),
    re.compile(r"\bas an ai\b", re.I),
    re.compile(r"\bi'?m here to help\b", re.I),
    re.compile(r"\blet me explain\b", re.I),
    re.compile(r"\bi understand your confusion\b", re.I),
    re.compile(r"\bcurrent objective\b", re.I),
    re.compile(r"\binternal state\b", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
]

_CONTRACTION_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bI am\b", re.I), "I'm"),
    (re.compile(r"\bwe are\b", re.I), "we're"),
    (re.compile(r"\byou are\b", re.I), "you're"),
    (re.compile(r"\bthey are\b", re.I), "they're"),
    (re.compile(r"\bit is\b", re.I), "it's"),
    (re.compile(r"\bthat is\b", re.I), "that's"),
    (re.compile(r"\bwould not\b", re.I), "wouldn't"),
    (re.compile(r"\bcannot\b", re.I), "can't"),
    (re.compile(r"\bdo not\b", re.I), "don't"),
    (re.compile(r"\bdoes not\b", re.I), "doesn't"),
    (re.compile(r"\bwill not\b", re.I), "won't"),
]

_SUBSTITUTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bThat (?:completely |really |truly )?"
            r"makes (?:a lot of )?sense[!.,]?\s*",
            re.I,
        ),
        "Makes sense. ",
    ),
    (
        re.compile(
            r"\bI (?:completely |totally )?"
            r"understand\b[^.!?]*[.!]\s*",
            re.I,
        ),
        "Gotcha. ",
    ),
    (
        re.compile(
            r"\bI (?:really )?get (?:it|that)[!.,]?\s*",
            re.I,
        ),
        "Got it. ",
    ),
    (
        re.compile(r"\bAbsolutely[!.,]?\s*", re.I),
        "Yeah. ",
    ),
    (
        re.compile(r"\bFor sure[!.,]?\s*", re.I),
        "Okay. ",
    ),
    (
        re.compile(
            r"\bCould you (?:please )?"
            r"(?:provide|give me|share|tell me) "
            r"(?:the )?(?:full |property )?address\?",
            re.I,
        ),
        "What's the address?",
    ),
    (
        re.compile(
            r"\bWhat is the (?:full |property )?address\?",
            re.I,
        ),
        "What's the address?",
    ),
    (
        re.compile(
            r"\bIs (?:the property|it) (?:currently )?vacant\?",
            re.I,
        ),
        "Vacant right now?",
    ),
    (
        re.compile(
            r"\bAre you (?:currently )?living (?:there|in it)\?",
            re.I,
        ),
        "Living there now?",
    ),
    (
        re.compile(
            r"\bDoes (?:it|the property) (?:currently )?need "
            r"(?:any|some|significant)? ?(?:work|repairs?|updating)\?",
            re.I,
        ),
        "Need much work?",
    ),
    (
        re.compile(
            r"\bHow (?:soon|quickly) (?:are|were) you "
            r"(?:looking|hoping|planning) to (?:sell|close|move)\?",
            re.I,
        ),
        "How soon you trying to move?",
    ),
    (
        re.compile(
            r"\bWhat(?:'s| is| was) your timeline"
            r"(?: for (?:this|the sale))?\?",
            re.I,
        ),
        "What's the timeline look like?",
    ),
    (
        re.compile(
            r"\bWhat (?:is|'s|are) you (?:looking|hoping) "
            r"to (?:get|walk away with)"
            r"(?: from (?:this|the sale))?\?",
            re.I,
        ),
        "What's your number?",
    ),
]

_AI_SETUP_PATTERNS = [
    re.compile(
        r"I'?d (?:love|like) to ask you "
        r"(?:a few |some |some quick )?questions?"
        r"(?:\s+about[^.?!]*)?\.\s*",
        re.I,
    ),
    re.compile(
        r"Before (?:I|we) can "
        r"(?:give you (?:a )?(?:number|ballpark|estimate|quote)"
        r"|make (?:you )?(?:an )?offer),\s*",
        re.I,
    ),
    re.compile(
        r"To (?:better )?(?:help|assist) you,?\s*",
        re.I,
    ),
]


def _strip_markdown(text: str) -> str:
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)

    return text


def _apply_substitutions(text: str) -> str:
    for pattern, replacement in _SUBSTITUTION_RULES:
        text = pattern.sub(replacement, text)

    return re.sub(r"\s{2,}", " ", text).strip()


def _strip_ai_setups(text: str) -> str:
    for pattern in _AI_SETUP_PATTERNS:
        text = pattern.sub("", text)

    return text.strip()


def _normalize_spacing(text: str) -> str:
    text = text.replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"([.!?])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\s+([.!?,])", r"\1", text)

    return text.strip()


def _humanize(text: str) -> str:
    text = text.strip()
    if not text:
        return "Okay."
    return text


class SpokenRendererProcessor(FrameProcessor):
    def __init__(self, call_ctx: CallContext) -> None:
        super().__init__()

        self._ctx = call_ctx
        self._buffer = ""

    def _transform(self, text: str) -> str:
        text = text.strip()

        if not text:
            return "Okay."

        for pattern in _LEAKAGE_PATTERNS:
            if pattern.search(text):
                logger.error(
                    "spoken_renderer leakage_blocked "
                    "pattern={} preview={!r}",
                    pattern.pattern,
                    text[:120],
                )

                return _LEAKAGE_SAFE

        for pattern in _META_BLOCK_PATTERNS:
            if pattern.search(text):
                logger.warning(
                    "spoken_renderer meta_blocked "
                    "pattern={} preview={!r}",
                    pattern.pattern,
                    text[:120],
                )

                return _META_SAFE

        text = _strip_markdown(text)

        for pattern, replacement in _CONTRACTION_MAP:
            text = pattern.sub(replacement, text)

        text = _apply_substitutions(text)
        text = _strip_ai_setups(text)
        text = _normalize_spacing(text)
        text = _humanize(text)

        return text or "Okay."

    async def _emit_fast(
        self,
        text: str,
        direction: FrameDirection,
    ) -> None:
        transformed = self._transform(text)

        if not transformed:
            return

        logger.info(
            "spoken_renderer turn={} in_chars={} out_chars={} preview={!r}",
            self._ctx.turn_count,
            len(text),
            len(transformed),
            transformed[:100],
        )

        await self.push_frame(
            TTSTextFrame(
                text=transformed,
                aggregated_by=AggregationType.SENTENCE,
            ),
            direction,
        )

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            self._buffer = ""

            await self.push_frame(frame, direction)

            return

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            incoming = frame.text or ""
            if not incoming.strip():
                return
            self._buffer += incoming
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            text = self._buffer.strip()

            self._buffer = ""

            if text:
                await self._emit_fast(
                    text,
                    direction,
                )

            await self.push_frame(
                frame,
                direction,
            )

            return

        await self.push_frame(
            frame,
            direction,
        )