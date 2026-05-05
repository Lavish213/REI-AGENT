import re
from dataclasses import dataclass, field

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


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


class ContextTrackerProcessor(FrameProcessor):
    def __init__(self, call_ctx: CallContext):
        super().__init__()
        self._ctx = call_ctx

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            self._analyze(frame.text)
            prefix = self._ctx.build_context_prefix()
            if prefix:
                try:
                    frame = TranscriptionFrame(
                        text=f"{prefix}\n\n{frame.text}",
                        user_id=frame.user_id,
                        timestamp=frame.timestamp,
                    )
                except Exception:
                    pass

        await self.push_frame(frame, direction)

    def _analyze(self, text: str):
        lower = text.lower()

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
