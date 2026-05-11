import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from pipecat.processors.aggregators.llm_context import LLMContext


@dataclass
class CallContext:
    seller_name: str | None = None
    opener_used: str | None = None
    last_opener_used: str | None = None
    current_phase: str = "PERMISSION"
    property_issues: list[str] = field(default_factory=list)
    motivation_signals: list[str] = field(default_factory=list)
    last_price_mentioned: int | None = None
    timeline_mentioned: str | None = None
    objections_raised: list[str] = field(default_factory=list)
    objections_handled: list[str] = field(default_factory=list)
    rapport_moments: list[str] = field(default_factory=list)
    current_emotion: str | None = None
    last_acknowledgment_used: str | None = None
    callback_time_mentioned: str | None = None
    talk_time_sophia: float = 0.0
    talk_time_caller: float = 0.0
    disposition: str | None = None
    extended_loaded: bool = False
    turn_count: int = 0

    def build_context_prefix(self) -> str:
        parts = []
        if self.seller_name:
            parts.append(f"seller name: {self.seller_name}")
        parts.append(f"phase: {self.current_phase}")
        if self.property_issues:
            parts.append(f"property issues: {', '.join(self.property_issues[-3:])}")
        if self.motivation_signals:
            parts.append(f"motivation: {', '.join(self.motivation_signals[-3:])}")
        if self.last_price_mentioned is not None:
            dollar = self.last_price_mentioned // 100
            parts.append(f"last price: ${dollar:,}")
        if self.timeline_mentioned:
            parts.append(f"timeline: {self.timeline_mentioned}")
        if self.objections_raised:
            parts.append(f"objections: {', '.join(self.objections_raised[-2:])}")
        if self.current_emotion:
            parts.append(f"caller sentiment: {self.current_emotion}")
        if self.disposition:
            parts.append(f"disposition: {self.disposition}")
        if not parts:
            return ""
        return "[CONTEXT: " + "; ".join(parts) + "]"


_ISSUE_PATTERNS = [
    (r"\b(roof|roofing|leak|leaking)\b", "roof problem"),
    (r"\b(foundation|crack|settling)\b", "foundation issue"),
    (r"\b(plumbing|pipes|water damage)\b", "plumbing issue"),
    (r"\b(hvac|ac|heat|furnace|air conditioning)\b", "HVAC issue"),
    (r"\b(mold|mildew|asbestos)\b", "environmental issue"),
    (r"\b(fire damage|flood|water damage)\b", "damage"),
    (r"\b(hoard|hoarding|junk|trash)\b", "condition issue"),
]

_MOTIVATION_PATTERNS = [
    (r"\b(need to sell|have to sell|must sell|selling fast|sell quickly)\b", "urgent to sell"),
    (r"\b(divorce|divorcing|separated|splitting)\b", "divorce"),
    (r"\b(foreclosure|behind on|missed payment|default)\b", "foreclosure risk"),
    (r"\b(inherited|estate|probate|passed away|died)\b", "inherited property"),
    (r"\b(relocating|moving|transfer|job)\b", "relocation"),
    (r"\b(tired landlord|bad tenant|eviction)\b", "landlord tired"),
    (r"\b(behind on taxes|tax lien|irs)\b", "tax issues"),
]

_OBJECTION_PATTERNS = [
    (r"\b(too low|not enough|worth more|higher offer)\b", "price too low"),
    (r"\b(agent|realtor|listing|mls|market)\b", "considering MLS"),
    (r"\b(think about it|need time|not ready)\b", "needs time"),
    (r"\b(other offer|someone else|another buyer)\b", "competing offer"),
]

_EXTENDED_PROCESS_PATTERN = re.compile(
    r"\b(how does (this|it) work|title company|what do i sign|how.?do i get paid|escrow|is this legal|purchase agreement|what happens (when|after|at)|who pays closing)\b",
    re.IGNORECASE,
)

_EXTENDED_LOCATION_PATTERN = re.compile(
    r"\b(south stockton|north stockton|weston ranch|lincoln village|march lane|hammer lane|flood zone|delta|lincoln unified|spanos|valley oak|brookside|lodi|tracy|manteca)\b",
    re.IGNORECASE,
)

_EXTENDED_SPANISH_PATTERN = re.compile(
    r"\b(hola|oye|buenos|buenas|espa[nñ]ol|hablas|habla|[oó]rale|sale|neta|ahorita|qu[eé] onda|[aá]ndale)\b",
    re.IGNORECASE,
)

_EXTENDED_SUBJECTTO_PATTERN = re.compile(
    r"\b(owe (too much|more than|a lot)|upside down|subject.?to|behind on (the )?mortgage|negative equity|underwater|not much equity)\b",
    re.IGNORECASE,
)

_EXTENDED_PROPERTY_PATTERN = re.compile(
    r"\b(solar|hoa|homeowners.?association|tenant|renter|lease|prop 13|proposition 13|property tax|transfer tax)\b",
    re.IGNORECASE,
)

_TIMELINE_PATTERN = re.compile(
    r"\b(asap|immediately|right away|next week|next month|30 days|60 days|90 days|few months|end of the year)\b",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(r"\$\s*(\d[\d,]*)\s*k?\b", re.IGNORECASE)


def _extract_price_cents(text: str) -> int | None:
    m = _PRICE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    val = int(raw)
    if "k" in m.group(0).lower():
        val *= 1000
    return val * 100


def _load_extended_prompt(extended_path: str) -> str:
    try:
        with open(extended_path) as f:
            return f.read().strip()
    except Exception:
        return ""


class ContextTrackerProcessor(FrameProcessor):
    def __init__(self, call_ctx: CallContext, llm_context=None, extended_prompt_path: str | None = None):
        super().__init__()
        self._ctx = call_ctx
        self._llm_context = llm_context
        self._extended_prompt_path = extended_prompt_path

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            self._analyze(frame.text)
            self._ctx.turn_count += 1
            if self._ctx.turn_count >= 6 and self._llm_context is not None:
                if len(self._llm_context.messages) > 6:
                    from backend.voice.context import compress_context
                    compressed = compress_context(self._llm_context.messages, self._ctx.current_phase)
                    self._llm_context.set_messages(compressed)
            prefix = self._ctx.build_context_prefix()
            if prefix and self._llm_context and self._llm_context.messages:
                sys_msg = self._llm_context.messages[0]
                content = sys_msg.get("content", "")
                content = re.sub(r'\s*\[CONTEXT:[^\]]*\]', '', content).rstrip()
                sys_msg["content"] = content + f"\n\n{prefix}"
                logger.debug("context_tracker injected into system msg prefix={}", prefix)
            logger.info("llm input turn={} text={!r}", self._ctx.turn_count, frame.text)

        await self.push_frame(frame, direction)

    def _maybe_load_extended(self, text: str) -> None:
        if self._ctx.extended_loaded or not self._llm_context or not self._extended_prompt_path:
            return
        if (
            _EXTENDED_PROCESS_PATTERN.search(text)
            or _EXTENDED_LOCATION_PATTERN.search(text)
            or _EXTENDED_SPANISH_PATTERN.search(text)
            or _EXTENDED_SUBJECTTO_PATTERN.search(text)
            or _EXTENDED_PROPERTY_PATTERN.search(text)
        ):
            content = _load_extended_prompt(self._extended_prompt_path)
            if content and self._llm_context.messages:
                self._llm_context.messages[0]["content"] += "\n\n" + content
                self._ctx.extended_loaded = True
                from loguru import logger
                logger.info("extended_prompt_loaded trigger_text={}", text[:60])

    def _analyze(self, text: str):
        lower = text.lower()

        self._maybe_load_extended(text)

        price = _extract_price_cents(text)
        if price is not None:
            self._ctx.last_price_mentioned = price

        m = _TIMELINE_PATTERN.search(lower)
        if m:
            self._ctx.timeline_mentioned = m.group(0)

        for pattern, label in _ISSUE_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.property_issues:
                self._ctx.property_issues.append(label)

        for pattern, label in _MOTIVATION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.motivation_signals:
                self._ctx.motivation_signals.append(label)

        for pattern, label in _OBJECTION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.objections_raised:
                self._ctx.objections_raised.append(label)
