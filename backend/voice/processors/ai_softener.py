"""
AISoftenerProcessor — post-LLM text transform that reduces AI-sounding patterns.

Addresses:
- Robotic ack phrases ("Certainly!", "Absolutely!", "Of course!")
- Over-perfect grammar
- Repeated filler phrases across turns
- Too-formal transitions

Wire AFTER sentence_streamer, BEFORE fair_housing_filter.
"""
from __future__ import annotations

import re
from collections import deque

from loguru import logger
from pipecat.frames.frames import Frame, TextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Robotic openers → natural replacements
_OPENER_MAP = [
    (re.compile(r"^Certainly[!,.]?\s*", re.I), ""),
    (re.compile(r"^Absolutely[!,.]?\s*", re.I), ""),
    (re.compile(r"^Of course[!,.]?\s*", re.I), ""),
    (re.compile(r"^Great[!,.]?\s*", re.I), ""),
    (re.compile(r"^Sure thing[!,.]?\s*", re.I), ""),
    (re.compile(r"^I understand[!,.]?\s*", re.I), "I hear you — "),
    (re.compile(r"^I completely understand[!,.]?\s*", re.I), "I get that — "),
    (re.compile(r"^That makes sense[!,.]?\s*", re.I), "Yeah that makes sense — "),
    (re.compile(r"^That's great[!,.]?\s*", re.I), ""),
    (re.compile(r"^That's wonderful[!,.]?\s*", re.I), ""),
    (re.compile(r"^How wonderful[!,.]?\s*", re.I), ""),
    (re.compile(r"^Wonderful[!,.]?\s*", re.I), ""),
    (re.compile(r"^Perfect[!,.]?\s*", re.I), ""),
    (re.compile(r"^Excellent[!,.]?\s*", re.I), ""),
    (re.compile(r"^Thank you for sharing that[!,.]?\s*", re.I), ""),
    (re.compile(r"^Thank you for (?:telling|letting) me know[!,.]?\s*", re.I), ""),
    (re.compile(r"^I appreciate you sharing that[!,.]?\s*", re.I), ""),
]

# Formal phrases → more natural
_INLINE_MAP = [
    (re.compile(r"\bI would like to\b", re.I), "I'd like to"),
    (re.compile(r"\bI am\b", re.I), "I'm"),
    (re.compile(r"\bwe are\b", re.I), "we're"),
    (re.compile(r"\bthey are\b", re.I), "they're"),
    (re.compile(r"\byou are\b", re.I), "you're"),
    (re.compile(r"\bit is\b", re.I), "it's"),
    (re.compile(r"\bthat is\b", re.I), "that's"),
    (re.compile(r"\bwould not\b", re.I), "wouldn't"),
    (re.compile(r"\bcannot\b", re.I), "can't"),
    (re.compile(r"\bdo not\b", re.I), "don't"),
    (re.compile(r"\bdoes not\b", re.I), "doesn't"),
    (re.compile(r"\bwill not\b", re.I), "won't"),
    (re.compile(r"\bAs an AI\b", re.I), ""),
    (re.compile(r"\bas your AI assistant\b", re.I), ""),
]

# Phrases to suppress if repeated in last N turns.
# Batch 4 doctrine: short acks (okay, yeah, gotcha) MUST repeat freely — that's realism.
# Only suppress multi-word constructions that sound formulaic when repeated.
_REPEATABLE_STARTERS = [
    "i hear you",
    "i completely understand",
    "that makes sense",
    "no worries",
    "makes sense",
]

_MAX_REPEAT_WINDOW = 6  # broader window — allow more repetition than before

# Setup/orchestration phrases that must never reach the caller
_LEAKAGE_PATTERNS = [
    re.compile(r"\[name\]", re.I),
    re.compile(r"\[address\]", re.I),
    re.compile(r"\binbound or outbound\b", re.I),
    re.compile(r"\bcall type\b", re.I),
    re.compile(r"\bright opening\b", re.I),
    re.compile(r"owner.{0,5}s name and address", re.I),
    re.compile(r"\bOUTBOUND\b"),
    re.compile(r"\bINBOUND\b"),
    re.compile(r"\bmax(imum)?\s+(offer|we\s+can\s+pay)\b", re.I),
    re.compile(r"\bour\s+max\s+is\b", re.I),
    re.compile(r"\bafter[- ]repair[- ]value\b", re.I),
    re.compile(r"\bARV\s+is\b", re.I),
    re.compile(r"\bdistress\s+score\b", re.I),
    re.compile(r"\b(claude|anthropic|openai|chatgpt|gpt-\d|gemini)\b", re.I),
    re.compile(r"\blead\s+score\b", re.I),
    re.compile(r"\bcomposite\s+score\b", re.I),
]

_INTERNAL_PROPERTY_LABEL = re.compile(
    r"(?:the\s+)?QA TEST ONLY\s*-\s*DO NOT CONTACT(?:\s+property)?",
    re.I,
)

_NO_QUESTION_GOALS = {
    "answer",
    "decline",
    "empathy",
    "goodbye",
    "human",
    "identity",
    "repair",
    "stop",
    "wait",
}

_QUESTION_TOPICS = [
    ("address", re.compile(r"\b(?:what(?:'s| is) the address|property address|where is the property)\b", re.I)),
    ("timeline", re.compile(r"\b(?:how soon|timeline|when .*sell|timing)\b", re.I)),
    ("condition", re.compile(r"\b(?:condition|repairs|shape)\b", re.I)),
    ("motivation", re.compile(r"\b(?:why .*sell|what.*prompting|considering selling)\b", re.I)),
    ("price", re.compile(r"\b(?:asking price|price|number in mind|looking to get)\b", re.I)),
]
_LEAKAGE_SAFE = "Hey, this is Sophia with San Joaquin House Buyers. Did I catch you at an okay time?"


def _apply_openers(text: str) -> str:
    for pattern, replacement in _OPENER_MAP:
        new_text = pattern.sub(replacement, text, count=1)
        if new_text != text:
            return new_text.lstrip()
    return text


def _apply_contractions(text: str) -> str:
    for pattern, replacement in _INLINE_MAP:
        text = pattern.sub(replacement, text)
    return text.strip()


def _extract_starter(text: str) -> str | None:
    lower = text.lower().strip()
    for s in _REPEATABLE_STARTERS:
        if lower.startswith(s):
            return s
    return None


class AISoftenerProcessor(FrameProcessor):
    """
    Post-processes LLM text output to sound more human and less robotic.
    Tracks recent openers to prevent repetition across turns.
    """

    def __init__(self, call_ctx=None, **kwargs):
        super().__init__(**kwargs)
        self._call_ctx = call_ctx
        self._recent_starters: deque[str] = deque(maxlen=_MAX_REPEAT_WINDOW)
        self._question_turns: dict[str, int] = {}
        self._turn_count = 0

    def _normalize_spoken_text(self, text: str) -> str:
        text = re.sub(r"(?:\s*[—–-]\s*){2,}", " — ", text)
        text = re.sub(r"([!?.,])\1+", r"\1", text)
        text = re.sub(r"\s+([!?.,])", r"\1", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _question_topic(self, text: str) -> str | None:
        for topic, pattern in _QUESTION_TOPICS:
            if pattern.search(text):
                return topic
        return None

    def _enforce_turn_contract(self, text: str) -> str:
        if self._call_ctx is None or "?" not in text:
            return text
        goal = getattr(self._call_ctx, "response_goal", "")
        if goal in _NO_QUESTION_GOALS:
            return re.sub(r"(?:^|(?<=[.!]))\s*[^.!?]*\?", "", text).strip()
        topic = self._question_topic(text)
        if topic is None:
            return text
        turn = int(getattr(self._call_ctx, "turn_count", 0))
        previous = self._question_turns.get(topic)
        if previous is not None and turn - previous <= 2:
            return re.sub(r"(?:^|(?<=[.!]))\s*[^.!?]*\?", "", text).strip()
        self._question_turns[topic] = turn
        return text

    def _soften(self, text: str) -> str:
        if not text or not text.strip():
            return text

        # Block setup/orchestration leakage before it reaches TTS
        for pattern in _LEAKAGE_PATTERNS:
            if pattern.search(text):
                logger.error(
                    "leakage_blocked pattern={} text_preview={}",
                    pattern.pattern,
                    text[:80],
                )
                return _LEAKAGE_SAFE

        original = text
        text = _INTERNAL_PROPERTY_LABEL.sub("the property", text)
        # Strip robotic openers
        text = _apply_openers(text)
        # Apply contractions
        text = _apply_contractions(text)
        text = self._normalize_spoken_text(text)
        text = self._enforce_turn_contract(text)

        # Check for repeated starters
        starter = _extract_starter(text)
        if starter and starter in self._recent_starters:
            # Remove the repeated starter
            idx = text.lower().find(starter)
            if idx == 0:
                text = text[len(starter):].lstrip(" ,")
                text = text[:1].upper() + text[1:] if text else text

        if starter:
            self._recent_starters.append(starter)

        if original != text:
            logger.debug("ai_softener modified text original_len={} new_len={}", len(original), len(text))

        return text

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (TextFrame, TTSTextFrame)):
            softened = self._soften(frame.text)
            if softened != frame.text:
                frame.text = softened
            self._turn_count += 1

        await self.push_frame(frame, direction)
