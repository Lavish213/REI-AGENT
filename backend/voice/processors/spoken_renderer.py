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
    from backend.voice.processors.context_tracker import CallContext


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

_LEAKAGE_SAFE = "Hey, this is Sophia with San Joaquin House Buyers."

_CONTRACTION_MAP = [
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

_SUBSTITUTION_RULES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\bThat (?:completely |really |truly )?makes (?:a lot of )?sense[!.,]?\s*",
            re.I,
        ),
        "Makes sense. ",
    ),
    (
        re.compile(
            r"\bI (?:completely |totally )?understand\b[^.!?]*[.!]\s*",
            re.I,
        ),
        "Gotcha. ",
    ),
    (
        re.compile(
            r"\bI (?:completely )?get (?:it|that)[!.,]?\s*",
            re.I,
        ),
        "Got it. ",
    ),
    (
        re.compile(
            r"\bI (?:really )?appreciate (?:you|your|that|it)[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bThank you for (?:sharing|letting me know|telling me)(?: that)?[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bAbsolutely[!.,]?\s*",
            re.I,
        ),
        "Yeah. ",
    ),
    (
        re.compile(
            r"\bCertainly[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bOf course[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bFor sure[!.,]?\s*",
            re.I,
        ),
        "Okay. ",
    ),
    (
        re.compile(
            r"\bNo worries[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bNo problem[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"(?:^|\s)(?:Great|Awesome|Wonderful|Excellent|Perfect)[!.,]?\s*",
            re.I,
        ),
        " ",
    ),
    (
        re.compile(
            r"\bI hear you[!.,]?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bFeel free to \w+[^.?!]*[.!]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bDon'?t hesitate to \w+[^.?!]*[.!]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bI'?m here to help[^.!]*[.!]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bI'?d be happy to help[^.!]*[.!]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bAs I mentioned,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bTo summarize,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bIn conclusion,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bMoving forward,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bWith that (?:being )?said,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bAdditionally,?\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bCould you (?:please )?(?:provide|give me|share|tell me) (?:the )?(?:full |property )?address\?",
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
            r"\bAre you (?:currently )?living (?:there|in the property|in it)\?",
            re.I,
        ),
        "Living there now?",
    ),
    (
        re.compile(
            r"\bDoes (?:it|the property) (?:currently )?need (?:any|some|significant)? ?(?:work|repairs?|updating)\?",
            re.I,
        ),
        "Need much work?",
    ),
    (
        re.compile(
            r"\bHow (?:soon|quickly) (?:are|were) you (?:looking|hoping|planning) to (?:sell|close|move)\?",
            re.I,
        ),
        "How soon you trying to move?",
    ),
    (
        re.compile(
            r"\bWhat(?:'s| is| was) your timeline(?: for (?:this|the sale))?\?",
            re.I,
        ),
        "What's the timeline look like?",
    ),
    (
        re.compile(
            r"\bWhat (?:is|'s|are) you (?:looking|hoping) to (?:get|walk away with)(?: from (?:this|the sale))?\?",
            re.I,
        ),
        "What's your number?",
    ),
    (
        re.compile(
            r"\bWhat kind of condition is the property in\?",
            re.I,
        ),
        "What kind of shape is it in?",
    ),
]

_AI_SETUP_PATTERNS = [
    re.compile(
        r"I'?d (?:love|like) to ask you (?:a few |some |some quick )?questions?(?:\s+about[^.?!]*)?\.\s*",
        re.I,
    ),
    re.compile(
        r"I(?:'d| would) (?:love|like) to (?:help you with that|assist(?:\s+you)?)\.\s*",
        re.I,
    ),
    re.compile(
        r"Before (?:I|we) can (?:give you (?:a )?(?:number|ballpark|estimate|quote)|make (?:you )?(?:an )?offer),\s*",
        re.I,
    ),
    re.compile(
        r"To (?:better )?(?:help|assist) you,?\s*",
        re.I,
    ),
]

_SENTENCE_BREAK_PATTERN = re.compile(
    r"([.!?])\s+"
)


def _apply_substitutions(text: str) -> str:
    for pattern, replacement in _SUBSTITUTION_RULES:
        text = pattern.sub(replacement, text)

    return re.sub(r"\s{2,}", " ", text).strip()


def _strip_ai_setups(text: str) -> str:
    for pattern in _AI_SETUP_PATTERNS:
        text = pattern.sub("", text)

    return text.strip()


def _humanize(text: str) -> str:
    text = text.strip()

    if not text:
        return "Okay."

    sentences = _SENTENCE_BREAK_PATTERN.split(text)
    rebuilt = []

    for chunk in sentences:
        if chunk:
            rebuilt.append(chunk)

    text = "".join(rebuilt)

    if len(text.split()) > 24:
        pieces = re.split(r"[.?!]", text)

        if len(pieces) > 1:
            text = pieces[0].strip()

    text = re.sub(r"\s{2,}", " ", text).strip()

    return text


class SpokenRendererProcessor(FrameProcessor):

    def __init__(self, call_ctx: CallContext):
        super().__init__()

        self._ctx = call_ctx
        self._buffer = ""
        self._last_emit = ""

    def _transform(self, text: str) -> str:
        for pattern in _LEAKAGE_PATTERNS:
            if pattern.search(text):
                logger.error(
                    "spoken_renderer leakage_blocked pattern={} preview={}",
                    pattern.pattern,
                    text[:80],
                )

                return _LEAKAGE_SAFE

        for pattern, replacement in _CONTRACTION_MAP:
            text = pattern.sub(replacement, text)

        text = _apply_substitutions(text)
        text = _strip_ai_setups(text)
        text = text.replace("\n", " ")
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = _humanize(text)

        if not text:
            return "Okay."

        return text

    async def _emit_fast(self, text: str, direction):
        transformed = self._transform(text)

        if not transformed:
            return

        if transformed == self._last_emit:
            return

        self._last_emit = transformed

        logger.info(
            "spoken_renderer turn={} in={} out={} preview={!r}",
            self._ctx.turn_count,
            len(text),
            len(transformed),
            transformed[:80],
        )

        await self.push_frame(
            TTSTextFrame(
                text=transformed,
                aggregated_by=AggregationType.SENTENCE,
            ),
            direction,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            self._buffer = ""

            await self.push_frame(frame, direction)

            return

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            incoming = frame.text or ""

            if not incoming:
                return

            self._buffer += incoming

            if (
                len(self._buffer) > 55
                or "?" in self._buffer
                or "." in self._buffer
            ):
                text = self._buffer.strip()
                self._buffer = ""

                await self._emit_fast(text, direction)

            return

        if isinstance(frame, LLMFullResponseEndFrame):
            text = self._buffer.strip()
            self._buffer = ""

            if text:
                await self._emit_fast(text, direction)

            await self.push_frame(frame, direction)

            return

        await self.push_frame(frame, direction)