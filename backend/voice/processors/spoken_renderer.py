"""
SpokenRendererProcessor — converts LLM output to realistic acquisitions operator speech.

Pipeline position: LLM → SpokenRenderer → AISoftener → TTS

Responsibilities:
- Buffers full LLM response (LLMTextFrame tokens → flush on LLMFullResponseEndFrame)
- Applies fragment compression (formal questions → spoken fragments)
- Prunes sentences based on pacing_state (warm=3 / operational=2 / tight=1)
- Detects AI-quality speech and scores it
- Forces rewrite if AI score too high
- Injects tactical silence for price/emotional moments
- Emits single TTSTextFrame per turn

Does NOT:
- Load extended prompts
- Modify system message
- Duplicate work done by AISoftenerProcessor
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    AggregationType,
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TextFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from backend.voice.processors.context_tracker import CallContext


# ---------------------------------------------------------------------------
# Fragment compression — formal questions → natural spoken fragments
# ---------------------------------------------------------------------------

_FRAGMENT_RULES: list[tuple[re.Pattern, str]] = [
    # Vacancy
    (re.compile(r"\bIs (?:the property|it) currently vacant\b[?]?", re.I), "Vacant right now?"),
    (re.compile(r"\bIs (?:the property|it) vacant\b[?]?", re.I), "Vacant right now?"),
    # Occupancy
    (re.compile(r"\bAre you (?:currently )?living (?:there|in the property)\b[?]?", re.I), "Living there now?"),
    (re.compile(r"\bIs (?:anyone|somebody|someone) (?:currently )?living (?:there|in the property|in it)\b[?]?", re.I), "Anyone living there?"),
    # Address
    (re.compile(r"\bCould you (?:provide|give me|share|tell me) the (?:full |property )?address\b[?]?", re.I), "What's the address?"),
    (re.compile(r"\bWhat is the (?:property )?address\b[?]?", re.I), "What's the address?"),
    # Condition
    (re.compile(r"\bDoes (?:it|the property) (?:currently )?need (?:any )?(?:significant )?(?:work|repairs?|updating|attention)\b[?]?", re.I), "Does it need work?"),
    # Timeline
    (re.compile(r"\bHow soon (?:are you|would you be) (?:looking to|wanting to|hoping to) (?:sell|move|close|complete this)\b[?]?", re.I), "How soon are you looking to move on this?"),
    # Intent
    (re.compile(r"\bWere you (?:actively )?(?:considering|thinking about|interested in) selling\b[?]?", re.I), "Were you thinking about selling, or not really?"),
]

# AI lead-in strippers — remove setup sentences before the actual question
_AI_SETUP_PATTERNS: list[re.Pattern] = [
    re.compile(r"I'd (?:love|like) to ask you (?:a few |some |some quick )?questions?(?:\s+about[^.?!]*)?\.\s*", re.I),
    re.compile(r"I(?:'d| would) (?:love|like) to (?:help you with that|assist(?:\s+you)?)\.\s*", re.I),
    re.compile(r"Before (?:I|we) can (?:give you (?:a )?(?:number|ballpark|rough estimate|quote)|make (?:you )?(?:an )?offer),\s*", re.I),
    re.compile(r"I want to make sure I (?:have|understand|get|gather)[^.]*\.\s*", re.I),
    re.compile(r"To (?:better )?(?:help|assist) you,?\s*", re.I),
    re.compile(r"I completely understand[^.]*\.\s*", re.I),
    re.compile(r"That (?:really )?makes (?:a lot of )?sense[.!]\s*", re.I),
]

# ---------------------------------------------------------------------------
# AI quality scoring
# ---------------------------------------------------------------------------

_AI_PENALTY_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\bI'?d be happy to\b", re.I), 3),
    (re.compile(r"\bI'?d love to\b", re.I), 3),
    (re.compile(r"\bI want to make sure\b", re.I), 2),
    (re.compile(r"\bI completely understand\b", re.I), 2),
    (re.compile(r"\bDoes that make sense\b", re.I), 2),
    (re.compile(r"\bIs there anything else\b", re.I), 3),
    (re.compile(r"\bFeel free to\b", re.I), 2),
    (re.compile(r"\butilize\b", re.I), 2),
    (re.compile(r"\bleverage\b", re.I), 1),
    (re.compile(r"\bensure\b", re.I), 1),
    (re.compile(r"\bprovide\b", re.I), 1),
    (re.compile(r"\bassist(?:ance)?\b", re.I), 2),
    (re.compile(r"\bI appreciate (?:you|your)\b", re.I), 2),
    (re.compile(r"\bThank you for (?:sharing|letting me know|telling me)\b", re.I), 3),
    (re.compile(r"\bOf course\b", re.I), 3),
    (re.compile(r"\bCertainly\b", re.I), 3),
    (re.compile(r"\bAbsolutely\b", re.I), 3),
    (re.compile(r"\bI'd like to (?:take|gather|understand|get|know)\b", re.I), 2),
    (re.compile(r"\bwould you be (?:open to|willing to|interested in)\b", re.I), 1),
]

_AI_SCORE_THRESHOLD = 5   # flag in logs
_AI_FORCE_THRESHOLD = 8   # attempt compression + truncate

# ---------------------------------------------------------------------------
# Silence timing (ms)
# ---------------------------------------------------------------------------

_SILENCE_MAP: dict[str, float] = {
    "price": 0.65,       # after seller gives a number
    "emotional": 0.85,   # after hardship disclosure
    "skeptical": 0.45,   # after skeptical comment
    "interruption": 0.20,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _max_sentences(pacing_state: str, seller_mode: str) -> int:
    """Return max allowed sentences based on pacing and seller mode."""
    if seller_mode == "HOT" or seller_mode == "FAST":
        return 1
    if seller_mode == "DISTRESSED" or seller_mode == "INHERITED" or seller_mode == "EMOTIONAL":
        return 3  # distressed sellers need space — override pacing tightening
    if pacing_state == "tight":
        return 1
    if pacing_state == "operational":
        return 2
    return 3  # warm


def _apply_fragments(text: str) -> str:
    for pattern, replacement in _FRAGMENT_RULES:
        text = pattern.sub(replacement, text)
    return text


def _strip_ai_setups(text: str) -> str:
    for pattern in _AI_SETUP_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()


def _score_ai_level(text: str) -> int:
    score = 0
    for pattern, penalty in _AI_PENALTY_PATTERNS:
        if pattern.search(text):
            score += penalty

    sentences = _split_sentences(text)

    # Long individual sentences = AI over-formality
    for s in sentences:
        if len(s.split()) > 15:
            score += 1

    # Too many sentences = AI over-completeness
    count = len(sentences)
    if count > 3:
        score += 2
    elif count > 2:
        score += 1

    return score


def _prune_sentences(text: str, max_s: int) -> str:
    sentences = _split_sentences(text)
    if len(sentences) <= max_s:
        return text
    # Keep last sentence if it contains a question (priority = question)
    pruned = sentences[:max_s]
    last_kept = pruned[-1]
    # If a question was dropped, check if it was the most important
    dropped = sentences[max_s:]
    questions = [s for s in dropped if s.endswith("?")]
    if questions and not last_kept.endswith("?"):
        # Replace last kept with the first dropped question
        pruned[-1] = questions[0]
    return " ".join(pruned)


# ---------------------------------------------------------------------------
# SpokenRendererProcessor
# ---------------------------------------------------------------------------

class SpokenRendererProcessor(FrameProcessor):
    """
    Post-LLM text transformation for realistic acquisitions speech.
    Buffers full LLM response and transforms before TTS.
    """

    def __init__(self, call_ctx: CallContext):
        super().__init__()
        self._ctx = call_ctx
        self._buffer = ""

    def _transform(self, text: str) -> str:
        original = text

        # 1. Strip AI setup sentences
        text = _strip_ai_setups(text)

        # 2. Apply fragment compression
        text = _apply_fragments(text)

        # 3. Prune to pacing-appropriate sentence count
        seller_mode = self._ctx.get_seller_mode()
        pacing = self._ctx.pacing_state
        max_s = _max_sentences(pacing, seller_mode)
        text = _prune_sentences(text, max_s)

        # 4. Score and log AI quality
        score = _score_ai_level(text)
        if score >= _AI_SCORE_THRESHOLD:
            logger.warning(
                "spoken_renderer ai_score={} turn={} text_preview={!r}",
                score,
                self._ctx.turn_count,
                text[:80],
            )

        if score >= _AI_FORCE_THRESHOLD:
            # Try stripping once more aggressively
            sentences = _split_sentences(text)
            # Keep only the last sentence (most likely the actual question)
            if sentences:
                text = sentences[-1]
            logger.warning(
                "spoken_renderer forced_truncation score={} final={!r}",
                score,
                text[:80],
            )

        # 5. Normalize whitespace
        text = re.sub(r"\s{2,}", " ", text).strip()

        if text != original:
            logger.debug(
                "spoken_renderer transformed original_len={} final_len={} score={}",
                len(original),
                len(text),
                score,
            )

        return text or original  # never return empty

    def _get_silence_delay(self) -> float:
        """Return tactical silence delay in seconds (0 if none needed)."""
        hint = self._ctx.silence_hint
        if hint and hint in _SILENCE_MAP:
            delay = _SILENCE_MAP[hint]
            self._ctx.silence_hint = None  # consume hint
            return delay
        return 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            self._buffer += frame.text or ""
            return  # buffer — do not push downstream yet

        if isinstance(frame, LLMFullResponseEndFrame):
            text = self._buffer.strip()
            self._buffer = ""

            if text:
                transformed = self._transform(text)

                silence_s = self._get_silence_delay()
                if silence_s > 0:
                    await asyncio.sleep(silence_s)

                logger.info(
                    "spoken_renderer turn={} pacing={} mode={} silence={:.0f}ms in={} out={}",
                    self._ctx.turn_count,
                    self._ctx.pacing_state,
                    self._ctx.get_seller_mode(),
                    silence_s * 1000,
                    len(text),
                    len(transformed),
                )

                await self.push_frame(
                    TTSTextFrame(text=transformed, aggregated_by=AggregationType.SENTENCE),
                    direction,
                )

            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
