from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_DIRECT_PATTERNS = re.compile(
    r"\b(just tell me|get to the point|how much|bottom line|"
    r"cut to the chase|what's the number|be straight with me)\b",
    re.IGNORECASE,
)

_STORYTELLER_PATTERNS = re.compile(
    r"\b(so what happened|let me explain|back when|the thing is|"
    r"it all started|you see|here's the situation|so basically)\b",
    re.IGNORECASE,
)

_ANALYTICAL_PATTERNS = re.compile(
    r"\b(how do you calculate|what's the process|can you explain|"
    r"how does that work|what's the formula|walk me through|"
    r"what are the steps|how do you determine)\b",
    re.IGNORECASE,
)

_GUARDED_PATTERNS = re.compile(
    r"\b(why do you need|why are you asking|that's personal|"
    r"I'd rather not|none of your business|why does that matter)\b",
    re.IGNORECASE,
)

_CRISIS_PATTERNS = re.compile(
    r"\b(foreclosure|auction|eviction|bankruptcy|can't pay|"
    r"losing the house|repo|garnished|shutoff)\b",
    re.IGNORECASE,
)

_SEVERE_PATTERNS = re.compile(
    r"\b(need the money|behind on bills|debt|medical bills|"
    r"laid off|lost my job|divorce|struggling)\b",
    re.IGNORECASE,
)

_MILD_PATTERNS = re.compile(
    r"\b(would be nice|could use the cash|thinking about it|"
    r"exploring options|not urgent but)\b",
    re.IGNORECASE,
)

_SAVVY_PATTERNS = re.compile(
    r"\b(ARV|after repair value|MAO|cap rate|comps|comparables|"
    r"investor margin|assignment fee|wholesale|flip)\b",
    re.IGNORECASE,
)

_NAIVE_PATTERNS = re.compile(
    r"\b(I don't know much|never done this|how does it work|"
    r"first time|not sure how|is this normal|what does that mean)\b",
    re.IGNORECASE,
)

_STYLE_CONFIDENCE_THRESHOLD = 2


class SellerProfileEngine(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._direct_count: int = 0
        self._storyteller_count: int = 0
        self._analytical_count: int = 0
        self._guarded_count: int = 0
        self._savvy_count: int = 0
        self._naive_count: int = 0
        self._profile_confidence: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_profile(text)

        await self.push_frame(frame, direction)

    def _update_profile(self, text: str) -> None:
        changed = False

        if _DIRECT_PATTERNS.search(text):
            self._direct_count += 1
            changed = True

        if _STORYTELLER_PATTERNS.search(text):
            self._storyteller_count += 1
            changed = True

        if _ANALYTICAL_PATTERNS.search(text):
            self._analytical_count += 1
            changed = True

        if _GUARDED_PATTERNS.search(text):
            self._guarded_count += 1
            changed = True

        if _SAVVY_PATTERNS.search(text):
            self._savvy_count += 1
            changed = True

        if _NAIVE_PATTERNS.search(text):
            self._naive_count += 1
            changed = True

        if _CRISIS_PATTERNS.search(text):
            if self._ctx.financial_pressure not in {"CRISIS", "SEVERE"}:
                self._ctx.financial_pressure = "CRISIS"
                logger.info("financial_pressure=CRISIS")

        elif _SEVERE_PATTERNS.search(text):
            if self._ctx.financial_pressure not in {"CRISIS", "SEVERE"}:
                self._ctx.financial_pressure = "SEVERE"
                logger.info("financial_pressure=SEVERE")

        elif _MILD_PATTERNS.search(text):
            if self._ctx.financial_pressure == "NONE":
                self._ctx.financial_pressure = "MILD"
                logger.info("financial_pressure=MILD")

        if not changed:
            return

        comm_style = self._derive_comm_style()
        if comm_style != self._ctx.comm_style:
            logger.info(
                "comm_style updated from={} to={} confidence={:.2f}",
                self._ctx.comm_style,
                comm_style,
                self._profile_confidence,
            )
            self._ctx.comm_style = comm_style

        sophistication = self._derive_sophistication()
        self._ctx.seller_sophistication = sophistication

        total_signals = (
            self._direct_count + self._storyteller_count
            + self._analytical_count + self._guarded_count
        )
        self._profile_confidence = min(1.0, total_signals * 0.15)

    def _derive_comm_style(self) -> str:
        counts = {
            "DIRECT": self._direct_count,
            "STORYTELLER": self._storyteller_count,
            "ANALYTICAL": self._analytical_count,
            "GUARDED": self._guarded_count,
        }
        top = max(counts, key=lambda k: counts[k])
        if counts[top] >= _STYLE_CONFIDENCE_THRESHOLD:
            return top
        return "STANDARD"

    def _derive_sophistication(self) -> str:
        if self._savvy_count >= 2:
            return "SAVVY"
        if self._savvy_count >= 1:
            return "INFORMED"
        if self._naive_count >= 2:
            return "NAIVE"
        return "AVERAGE"