from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_TRUST_BUILD: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(okay|alright|makes sense|that's fair|sounds reasonable)\b", re.IGNORECASE), 0.3),
    (re.compile(r"\b(how does it work|tell me more|what happens next|walk me through)\b", re.IGNORECASE), 0.8),
    (re.compile(r"\b(when can you come|let's do it|what's the offer|I'm ready)\b", re.IGNORECASE), 1.2),
    (re.compile(r"\b(my neighbor|someone told me|I heard you guys|a friend)\b", re.IGNORECASE), 0.6),
    (re.compile(r"\b(you seem|you sound|easy to talk to|appreciate)\b", re.IGNORECASE), 0.5),
    (re.compile(r"\b(honestly|to be honest|between us|I'll tell you)\b", re.IGNORECASE), 0.5),
    (re.compile(r"\b(my wife|my husband|my kids|my family|we've been here|grew up here)\b", re.IGNORECASE), 0.4),
]

_TRUST_ERODE: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(scam|fraud|fake|not real|is this legit)\b", re.IGNORECASE), 1.5),
    (re.compile(r"\b(how did you get my number)\b", re.IGNORECASE), 0.8),
    (re.compile(r"\b(sounds too good|I've heard this before|every investor says)\b", re.IGNORECASE), 1.0),
    (re.compile(r"\b(I need to check you out|look you up|verify)\b", re.IGNORECASE), 0.7),
    (re.compile(r"\b(not comfortable|not sure about this|something feels off)\b", re.IGNORECASE), 0.8),
    (re.compile(r"\b(stop calling|remove me|do not call|leave me alone)\b", re.IGNORECASE), 2.0),
    (re.compile(r"\b(are you a robot|are you AI|is this automated)\b", re.IGNORECASE), 1.2),
    (re.compile(r"\b(I'll think about it|call me later|not right now)\b", re.IGNORECASE), 0.3),
]

_LEGITIMACY_CHALLENGE: re.Pattern = re.compile(
    r"\b(who are you|what company|prove it|are you licensed|"
    r"real buyers|send me something|I want it in writing)\b",
    re.IGNORECASE,
)

_SCORE_MIN = 0.0
_SCORE_MAX = 10.0
_LEGITIMACY_PENALTY = 1.0
_BROKE_TRUST_THRESHOLD = 2.0
_CONSECUTIVE_ERODE_LIMIT = 3


class TrustTracker(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._prev_score: float = call_ctx.trust_score
        self._legitimacy_challenges: int = 0
        self._consecutive_erode: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_trust(text)

        await self.push_frame(frame, direction)

    def _update_trust(self, text: str) -> None:
        score = self._ctx.trust_score
        delta = 0.0

        for pattern, amount in _TRUST_BUILD:
            if pattern.search(text):
                delta += amount

        for pattern, amount in _TRUST_ERODE:
            if pattern.search(text):
                delta -= amount

        if _LEGITIMACY_CHALLENGE.search(text):
            self._legitimacy_challenges += 1
            delta -= _LEGITIMACY_PENALTY
            logger.info(
                "legitimacy_challenge count={}",
                self._legitimacy_challenges,
            )

        if delta < 0:
            self._consecutive_erode += 1
        elif delta > 0:
            self._consecutive_erode = 0

        score = max(_SCORE_MIN, min(_SCORE_MAX, score + delta))

        if score < _BROKE_TRUST_THRESHOLD and self._legitimacy_challenges >= 2:
            if not getattr(self._ctx, "_broke_trust_logged", False):
                logger.warning("trust_broken legitimacy_challenges={}", self._legitimacy_challenges)
                self._ctx._broke_trust_logged = True

        if abs(score - self._prev_score) > 0.1:
            logger.info(
                "trust_score updated score={:.2f} delta={:.2f} consecutive_erode={}",
                score,
                delta,
                self._consecutive_erode,
            )

        self._prev_score = score
        self._ctx.trust_score = score