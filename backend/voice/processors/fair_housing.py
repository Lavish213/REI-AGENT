import re

from loguru import logger

from pipecat.frames.frames import Frame, LLMTextFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_NEUTRAL_REPLACEMENT = "That area has a solid market for what we do."

_DEMOGRAPHIC_WORDS = re.compile(
    r"\b(race|racial|ethnicity|ethnic|religion|religious|national origin|"
    r"hispanic|latino|latina|black|white|asian|arab|jewish|muslim|christian|immigrant)\b",
    re.IGNORECASE,
)

_NEIGHBORHOOD_QUALITY = re.compile(
    r"\b(good neighborhood|bad neighborhood|nice neighborhood)\b",
    re.IGNORECASE,
)

_BANNED_PHRASES = re.compile(
    r"\b(crime rate|type of people|those people|that kind of area|changing neighborhood)\b",
    re.IGNORECASE,
)

_SCHOOL_DEMOGRAPHIC = re.compile(
    r"\b(school quality|school district|schools (are|were|used to))\b",
    re.IGNORECASE,
)


def _is_fair_housing_violation(text: str) -> bool:
    if _BANNED_PHRASES.search(text):
        return True
    if _NEIGHBORHOOD_QUALITY.search(text) and _DEMOGRAPHIC_WORDS.search(text):
        return True
    if _SCHOOL_DEMOGRAPHIC.search(text) and _DEMOGRAPHIC_WORDS.search(text):
        return True
    return False


class FairHousingFilter(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TextFrame)):
            text = frame.text if hasattr(frame, "text") else ""
            if _is_fair_housing_violation(text):
                logger.warning(
                    "fair_housing violation detected original_text={!r}", text
                )
                replacement_frame = TextFrame(text=_NEUTRAL_REPLACEMENT)
                await self.push_frame(replacement_frame, direction)
                return

        await self.push_frame(frame, direction)
