from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_TIMELINE_URGENT = re.compile(
    r"\b(asap|immediately|right away|as soon as possible|"
    r"within the (week|month)|30 days|need to move fast|"
    r"running out of time|deadline|very soon|no time)\b",
    re.IGNORECASE,
)

_TIMELINE_MODERATE = re.compile(
    r"\b(60 days|90 days|few months|couple months|"
    r"end of the (year|month)|this (summer|fall|spring|winter))\b",
    re.IGNORECASE,
)

_DISTRESS_SIGNALS = re.compile(
    r"\b(foreclosure|auction|behind on|missed payments|"
    r"divorce|can't afford|losing the house|eviction|"
    r"bankruptcy|need the cash|need money fast)\b",
    re.IGNORECASE,
)

_VACANCY_SIGNALS = re.compile(
    r"\b(vacant|empty|nobody living|unoccupied|sitting empty|"
    r"tenants left|no one there|abandoned)\b",
    re.IGNORECASE,
)

_FREE_CLEAR_SIGNALS = re.compile(
    r"\b(free and clear|no mortgage|paid off|own it outright|"
    r"no loan|no liens|fully paid)\b",
    re.IGNORECASE,
)

_PRICE_INQUIRY = re.compile(
    r"\b(what would you (offer|pay)|how much (would you|can you|do you)|"
    r"what('s| is) your offer|give me a number|make me an offer)\b",
    re.IGNORECASE,
)

_PROCESS_INQUIRY = re.compile(
    r"\b(how does it work|what's the process|how long does it take|"
    r"what happens next|walk me through|how do you|what do you need)\b",
    re.IGNORECASE,
)

_SOFT_ENGAGEMENT = re.compile(
    r"\b(tell me more|I'm listening|go ahead|sounds interesting|"
    r"I'm open to it|could work|might consider|depends)\b",
    re.IGNORECASE,
)

_AGENT_SIGNALS = re.compile(
    r"\b(agent|realtor|listed|on the mls|broker|already listed)\b",
    re.IGNORECASE,
)

_HARD_NO_SIGNALS = re.compile(
    r"\b(not interested|stop calling|never selling|remove me|"
    r"do not call|not selling|keeping it)\b",
    re.IGNORECASE,
)

_HIGH_MORTGAGE_SIGNALS = re.compile(
    r"\b(still owe a lot|underwater|owe more than|negative equity|"
    r"barely breaking even|lot left on the mortgage)\b",
    re.IGNORECASE,
)

_SCORE_MIN = 0.0
_SCORE_MAX = 10.0
_ON_FIRE_THRESHOLD = 8.0
_HOT_THRESHOLD = 6.0
_WARM_THRESHOLD = 3.0


def _score_to_level(score: float) -> str:
    if score >= _ON_FIRE_THRESHOLD:
        return "ON_FIRE"
    if score >= _HOT_THRESHOLD:
        return "HOT"
    if score >= _WARM_THRESHOLD:
        return "WARM"
    return "COLD"


class DealHeatScorer(FrameProcessor):
    def __init__(self, call_ctx):
        super().__init__()
        self._ctx = call_ctx
        self._score: float = 0.0
        self._prev_level: str = "COLD"

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()
            if text:
                self._update_heat(text)

        await self.push_frame(frame, direction)

    def _update_heat(self, text: str) -> None:
        delta = 0.0

        if _TIMELINE_URGENT.search(text):
            delta += 2.5
            logger.debug("deal_heat +2.5 timeline_urgent")
        elif _TIMELINE_MODERATE.search(text):
            delta += 1.5
            logger.debug("deal_heat +1.5 timeline_moderate")

        if _DISTRESS_SIGNALS.search(text):
            delta += 1.5
            logger.debug("deal_heat +1.5 distress")

        if _VACANCY_SIGNALS.search(text):
            delta += 1.0
            logger.debug("deal_heat +1.0 vacancy")

        if _FREE_CLEAR_SIGNALS.search(text):
            delta += 1.5
            logger.debug("deal_heat +1.5 free_and_clear")

        if _PRICE_INQUIRY.search(text):
            delta += 2.5
            logger.debug("deal_heat +2.5 price_inquiry")

        if _PROCESS_INQUIRY.search(text):
            delta += 1.5
            logger.debug("deal_heat +1.5 process_inquiry")

        if _SOFT_ENGAGEMENT.search(text):
            delta += 0.5
            logger.debug("deal_heat +0.5 soft_engagement")

        if not getattr(self._ctx, "has_agent", False) and not _AGENT_SIGNALS.search(text):
            delta += 0.3

        if _AGENT_SIGNALS.search(text):
            delta -= 2.0
            logger.debug("deal_heat -2.0 agent_detected")

        if _HARD_NO_SIGNALS.search(text):
            delta -= 3.0
            logger.debug("deal_heat -3.0 hard_no")

        if _HIGH_MORTGAGE_SIGNALS.search(text):
            delta -= 1.5
            logger.debug("deal_heat -1.5 high_mortgage")

        self._score = max(_SCORE_MIN, min(_SCORE_MAX, self._score + delta))
        level = _score_to_level(self._score)

        if level != self._prev_level:
            logger.info(
                "deal_heat level changed from={} to={} score={:.1f}",
                self._prev_level,
                level,
                self._score,
            )

        self._prev_level = level
        self._ctx.deal_heat = self._score
        self._ctx.deal_heat_level = level