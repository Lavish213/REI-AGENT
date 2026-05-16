"""
SpokenRendererProcessor — converts LLM output to realistic acquisitions operator speech.

Pipeline position: LLM → SpokenRenderer → AISoftener → TTS

Batch 3: fragment compression, sentence pruning, AI scoring, silence injection
Batch 4: unified substitution engine, word-count energy caps, redirect override,
         V2 AI scoring (service tone, over-completion, fake enthusiasm)

Transformation order inside _transform():
  1. Redirect override    — if redirect_needed, inject pivot phrase immediately
  2. Substitution rules   — replace AI phrases with bank equivalents
  3. AI setup stripping   — remove lead-in sentences ("I'd love to ask...")
  4. Energy cap           — enforce word count limit by pacing × seller_mode
  5. Sentence pruning     — enforce sentence count limit
  6. V2 AI scoring        — comprehensive AI quality check
  7. Force truncation     — if score >= threshold, keep last sentence only
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
# Unified substitution rules
# Applied in order — first match wins for each pattern
# Covers: AI acks → compact, service tone → delete, formal Q → fragment
# ---------------------------------------------------------------------------

_SUBSTITUTION_RULES: list[tuple[re.Pattern, str]] = [
    # --- Redundant ack phrases → compact or delete ---
    (re.compile(r"\bThat (?:completely |really |truly )?makes (?:a lot of )?sense[!.,]?\s*", re.I), "Makes sense. "),
    (re.compile(r"\bI (?:completely |totally )?understand\b[^.!?]*[.!]\s*", re.I), "Gotcha. "),
    (re.compile(r"\bI (?:completely )?get (?:it|that)[!.,]?\s*", re.I), "Got it. "),
    (re.compile(r"\bI (?:really )?appreciate (?:you|your|that|it)[!.,]?\s*", re.I), ""),
    (re.compile(r"\bThank you for (?:sharing|letting me know|telling me)(?: that)?[!.,]?\s*", re.I), ""),
    (re.compile(r"\bOf course[!.,]?\s*", re.I), ""),
    (re.compile(r"\bAbsolutely[!.,]?\s*", re.I), ""),
    (re.compile(r"\bCertainly[!.,]?\s*", re.I), ""),
    (re.compile(r"\bFor sure[!.,]?\s*", re.I), "Okay. "),
    (re.compile(r"\bNo worries[!.,]?\s*", re.I), ""),
    (re.compile(r"\bNo problem[!.,]?\s*", re.I), ""),
    (re.compile(r"(?:^|\s)(?:Great|Awesome|Wonderful|Excellent|Perfect)[!.,]?\s*", re.I), " "),
    (re.compile(r"\bI hear you[!.,]?\s*", re.I), "I hear you. "),

    # --- Service tone → delete ---
    (re.compile(r"\bFeel free to \w+[^.?!]*[.!]\s*", re.I), ""),
    (re.compile(r"\bDon'?t hesitate to \w+[^.?!]*[.!]\s*", re.I), ""),
    (re.compile(r"\bI'?m here to help[^.!]*[.!]\s*", re.I), ""),
    (re.compile(r"\bI'?d be happy to help[^.!]*[.!]\s*", re.I), ""),
    (re.compile(r"\bIs there anything else[^?]*\?\s*", re.I), ""),

    # --- Over-polite transitions → delete ---
    (re.compile(r"\bAs I mentioned,?\s*", re.I), ""),
    (re.compile(r"\bTo summarize,?\s*", re.I), ""),
    (re.compile(r"\bIn conclusion,?\s*", re.I), ""),
    (re.compile(r"\bMoving forward,?\s*", re.I), ""),
    (re.compile(r"\bWith that (?:being )?said,?\s*", re.I), ""),
    (re.compile(r"\bAdditionally,?\s*", re.I), ""),

    # --- Formal questions → spoken fragments ---
    (re.compile(r"\bCould you (?:please )?(?:provide|give me|share|tell me) (?:the )?(?:full |property )?address\?", re.I), "What's the address?"),
    (re.compile(r"\bWhat is the (?:full |property )?address\?", re.I), "What's the address?"),
    (re.compile(r"\bIs (?:the property|it) (?:currently )?vacant\?", re.I), "Vacant right now?"),
    (re.compile(r"\bAre you (?:currently )?living (?:there|in the property|in it)\?", re.I), "Living there now?"),
    (re.compile(r"\bIs (?:anyone|someone|somebody) (?:currently )?(?:living|residing) (?:there|in the property|in it)\?", re.I), "Anyone living there?"),
    (re.compile(r"\bDoes (?:it|the property) (?:currently )?need (?:any|some|significant)? ?(?:work|repairs?|updating)\?", re.I), "Need much work?"),
    (re.compile(r"\bHow (?:soon|quickly) (?:are|were) you (?:looking|hoping|planning) to (?:sell|close|move)\?", re.I), "How soon you trying to move?"),
    (re.compile(r"\bWhat(?:'s| is| was) your timeline(?: for (?:this|the sale))?\?", re.I), "What's the timeline look like?"),
    (re.compile(r"\bWhat (?:is|'s|are) you (?:looking|hoping) to (?:get|walk away with)(?: from (?:this|the sale))?\?", re.I), "What's your number?"),
    (re.compile(r"\bWhat (?:would|do) you (?:need|want) to (?:walk away with|net)(?: from (?:this|the sale))?\?", re.I), "What's your number?"),
    (re.compile(r"\bWere you (?:considering|thinking about) selling\?", re.I), "You thinking about selling?"),
    (re.compile(r"\bWere you (?:actively )?(?:looking|planning) to sell\?", re.I), "You thinking about selling?"),
    (re.compile(r"\bWhat (?:is|'s|was) the (?:current )?condition (?:of the property|of it)\?", re.I), "What kind of shape is it in?"),
]

# ---------------------------------------------------------------------------
# AI setup strippers — remove entire lead-in sentences before the actual point
# ---------------------------------------------------------------------------

_AI_SETUP_PATTERNS: list[re.Pattern] = [
    re.compile(r"I'?d (?:love|like) to ask you (?:a few |some |some quick )?questions?(?:\s+about[^.?!]*)?\.\s*", re.I),
    re.compile(r"I(?:'d| would) (?:love|like) to (?:help you with that|assist(?:\s+you)?)\.\s*", re.I),
    re.compile(r"Before (?:I|we) can (?:give you (?:a )?(?:number|ballpark|rough estimate|quote)|make (?:you )?(?:an )?offer),\s*", re.I),
    re.compile(r"I want to make sure I (?:have|understand|get|gather)[^.]*\.\s*", re.I),
    re.compile(r"To (?:better )?(?:help|assist) you,?\s*", re.I),
    re.compile(r"I'?d love to (?:understand|learn|know) (?:more about|about) (?:your|the)[^.]*\.\s*", re.I),
]

# ---------------------------------------------------------------------------
# AI quality scoring — V1 + V2 patterns
# ---------------------------------------------------------------------------

_AI_PENALTY_PATTERNS: list[tuple[re.Pattern, int]] = [
    # V1 — obvious AI phrases
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
    (re.compile(r"\bI'?d like to (?:take|gather|understand|get|know)\b", re.I), 2),
    (re.compile(r"\bwould you be (?:open to|willing to|interested in)\b", re.I), 1),

    # V2 — service tone / over-completion / fake enthusiasm
    (re.compile(r"\bI (?:want|wanted) to (?:make sure|let you know|inform)\b", re.I), 2),
    (re.compile(r"\byou'?d like\b", re.I), 1),
    (re.compile(r"\byou'?d want\b", re.I), 1),
    (re.compile(r"\bwhat I'?d suggest\b", re.I), 2),
    (re.compile(r"\bwhat I'?d recommend\b", re.I), 2),
    (re.compile(r"\bdon'?t hesitate\b", re.I), 3),
    (re.compile(r"\bhowever\b", re.I), 1),
    (re.compile(r"\btherefore\b", re.I), 2),
    (re.compile(r"\bas a result\b", re.I), 2),
    (re.compile(r"\bmoving forward\b", re.I), 2),
    (re.compile(r"\bwith that (?:being )?said\b", re.I), 2),
    (re.compile(r"[!](?!\?)", re.I), 1),  # exclamation = fake enthusiasm
    (re.compile(r"\bjust to (?:clarify|confirm|make sure)\b", re.I), 2),
    (re.compile(r"\bgreat (?:question|point)\b", re.I), 3),
    (re.compile(r"\bexcellent (?:question|point)\b", re.I), 3),
    (re.compile(r"\b(?:sound|seems?) like a plan\b", re.I), 1),
]

_AI_SCORE_THRESHOLD = 5
_AI_FORCE_THRESHOLD = 8

# ---------------------------------------------------------------------------
# Silence timing (seconds)
# ---------------------------------------------------------------------------

_SILENCE_MAP: dict[str, float] = {
    "price": 0.65,
    "emotional": 0.85,
    "skeptical": 0.45,
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
    if seller_mode in ("HOT", "FAST"):
        return 1
    if seller_mode in ("DISTRESSED", "INHERITED", "EMOTIONAL"):
        return 3
    if pacing_state == "tight":
        return 1
    if pacing_state == "operational":
        return 2
    return 3  # warm


def _word_cap(pacing_state: str, seller_mode: str) -> int:
    """Max words per response by stage. Enforces energy economy."""
    if seller_mode in ("HOT", "FAST"):
        return 12
    if seller_mode in ("DISTRESSED", "INHERITED", "EMOTIONAL"):
        return 30
    if pacing_state == "tight":
        return 15
    if pacing_state == "operational":
        return 22
    return 35  # warm


def _apply_substitutions(text: str) -> str:
    for pattern, replacement in _SUBSTITUTION_RULES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _strip_ai_setups(text: str) -> str:
    for pattern in _AI_SETUP_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()


def _apply_energy_cap(text: str, cap: int) -> str:
    words = text.split()
    if len(words) <= cap:
        return text
    truncated = " ".join(words[:cap])
    # Find last sentence boundary within the truncated text
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in ".?!":
            result = truncated[:i + 1].strip()
            if result:
                return result
    return truncated


def _score_ai_level(text: str) -> int:
    score = 0
    for pattern, penalty in _AI_PENALTY_PATTERNS:
        if pattern.search(text):
            score += penalty

    sentences = _split_sentences(text)
    for s in sentences:
        if len(s.split()) > 15:
            score += 1

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
    pruned = sentences[:max_s]
    dropped = sentences[max_s:]
    # Preserve dropped questions
    questions = [s for s in dropped if s.endswith("?")]
    if questions and not pruned[-1].endswith("?"):
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
        seller_mode = self._ctx.get_seller_mode()
        pacing = self._ctx.pacing_state

        # 1. Redirect override — seller was rambling, force pivot to objective
        if self._ctx.redirect_needed:
            self._ctx.redirect_needed = False  # consume flag
            from backend.voice.phrases import PIVOT_BANK, REDIRECT_BANK
            import random
            objective = self._ctx.get_current_objective()
            pivots = PIVOT_BANK.get(objective, REDIRECT_BANK)
            pivot = random.choice(pivots[:3])  # pick from top 3
            logger.info(
                "spoken_renderer redirect_override obj={} pivot={!r}",
                objective,
                pivot,
            )
            return pivot

        # 2. Apply substitution rules (AI phrases → bank equivalents)
        text = _apply_substitutions(text)

        # 3. Strip AI setup sentences
        text = _strip_ai_setups(text)

        # 4. Enforce word count energy cap
        cap = _word_cap(pacing, seller_mode)
        text = _apply_energy_cap(text, cap)

        # 5. Prune to pacing-appropriate sentence count
        max_s = _max_sentences(pacing, seller_mode)
        text = _prune_sentences(text, max_s)

        # 6. Score AI quality
        score = _score_ai_level(text)
        if score >= _AI_SCORE_THRESHOLD:
            logger.warning(
                "spoken_renderer ai_score={} turn={} text_preview={!r}",
                score,
                self._ctx.turn_count,
                text[:80],
            )

        # 7. Force truncation at high score — keep last sentence (likely the question)
        if score >= _AI_FORCE_THRESHOLD:
            sentences = _split_sentences(text)
            if sentences:
                text = sentences[-1]
            logger.warning(
                "spoken_renderer forced_truncation score={} final={!r}",
                score,
                text[:80],
            )

        text = re.sub(r"\s{2,}", " ", text).strip()

        if text != original:
            logger.debug(
                "spoken_renderer transformed original_len={} final_len={} score={} cap={}",
                len(original),
                len(text),
                score,
                cap,
            )

        if not text:
            # All content was AI noise — inject objective pivot rather than returning AI text
            from backend.voice.phrases import PIVOT_BANK
            objective = self._ctx.get_current_objective()
            pivots = PIVOT_BANK.get(objective, [])
            fallback = pivots[0] if pivots else "Okay."
            logger.warning(
                "spoken_renderer empty_after_transform obj={} fallback={!r}",
                objective,
                fallback,
            )
            return fallback

        return text

    def _get_silence_delay(self) -> float:
        hint = self._ctx.silence_hint
        if hint and hint in _SILENCE_MAP:
            delay = _SILENCE_MAP[hint]
            self._ctx.silence_hint = None
            return delay
        return 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            self._buffer += frame.text or ""
            return

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
