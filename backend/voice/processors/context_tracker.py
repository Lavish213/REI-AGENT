import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


ConversationPhase = Literal[
    "opening",
    "discovery",
    "negotiation",
    "objection_handling",
    "close_attempt",
    "wrap_up",
]

_PHASE_ORDER = [
    "opening",
    "discovery",
    "negotiation",
    "objection_handling",
    "close_attempt",
    "wrap_up",
]

SellerEnergy = Literal[
    "calm",
    "skeptical",
    "rushed",
    "motivated",
    "hesitant",
]

SituationLabel = Literal[
    "inherited_property",
    "tired_landlord",
    "probate",
    "preforeclosure",
    "relocation",
    "divorce",
    "downsizing",
    "vacant_property",
    "distressed_seller",
    "unknown",
]

_INTENT_PHRASES = [
    "trying to sell",
    "want to sell",
    "need to sell",
    "looking to sell",
    "selling my house",
    "sell fast",
    "sell the house",
    "sell my home",
    "get rid of it",
    "need to move",
    "have to sell",
    "must sell",
]

_ADDRESS_PATTERN = re.compile(
    r"\b\d{3,5}\s+[A-Za-z][\w\s]{2,30}"
    r"(?:st|ave|blvd|dr|ln|rd|ct|way|pl|cir|ter|"
    r"street|avenue|boulevard|drive|lane|road|"
    r"court|place|circle|terrace)\b",
    re.IGNORECASE,
)

_TIMELINE_PATTERN = re.compile(
    r"\b("
    r"asap|immediately|today|tomorrow|next week|"
    r"30 days|60 days|90 days|few months|this week"
    r")\b",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(
    r"(?:\$?\s*(\d{2,3}(?:,\d{3})+|\d{2,6})\s*(k|thousand|grand)?)",
    re.IGNORECASE,
)

_ISSUE_PATTERNS = [
    (r"\b(roof|roofing|leak|leaking)\b", "roof"),
    (r"\b(foundation|crack|settling)\b", "foundation"),
    (r"\b(plumbing|pipes|water damage)\b", "plumbing"),
    (r"\b(hvac|furnace|air conditioning)\b", "hvac"),
    (r"\b(mold|asbestos)\b", "environmental"),
    (r"\b(fire damage|flood)\b", "damage"),
    (r"\b(hoard|junk|trash|mess)\b", "condition"),
]

_MOTIVATION_PATTERNS = [
    (r"\b(need to sell|must sell|sell fast|asap)\b", "urgent"),
    (r"\b(divorce|divorcing)\b", "divorce"),
    (r"\b(foreclosure|behind on|auction)\b", "foreclosure"),
    (r"\b(inherited|estate|probate|passed away)\b", "inheritance"),
    (r"\b(relocating|moving|job transfer)\b", "relocation"),
    (r"\b(bad tenant|tenant|renter)\b", "landlord"),
]

_OBJECTION_PATTERNS = [
    (r"\b(too low|worth more|higher offer)\b", "price"),
    (r"\b(agent|realtor|listing|mls)\b", "mls"),
    (r"\b(think about it|need time|not ready)\b", "hesitation"),
    (r"\b(other offer|another buyer)\b", "competition"),
    (r"\b(not interested|stop calling)\b", "not interested"),
]

_PHASE_TRIGGERS: list[tuple[ConversationPhase, re.Pattern]] = [
    (
        "discovery",
        re.compile(
            r"\b(roof|foundation|tenant|repairs|condition|vacant|inherited)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "negotiation",
        re.compile(
            r"\b(how much|offer|price|what would you pay|make me an offer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "objection_handling",
        re.compile(
            r"\b(too low|not interested|need time|agent|listing)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "close_attempt",
        re.compile(
            r"\b(appointment|schedule|come see|walkthrough|meet)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "wrap_up",
        re.compile(
            r"\b(bye|goodbye|talk later|thanks)\b",
            re.IGNORECASE,
        ),
    ),
]

_ENERGY_PATTERNS: list[tuple[SellerEnergy, re.Pattern]] = [
    (
        "rushed",
        re.compile(
            r"\b(gotta go|busy|quick|in a hurry)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "skeptical",
        re.compile(
            r"\b(not sure|sounds too good|is this legit|scam)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "motivated",
        re.compile(
            r"\b(i'm ready|sounds good|let's do it|definitely)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hesitant",
        re.compile(
            r"\b(maybe|i guess|not sure if)\b",
            re.IGNORECASE,
        ),
    ),
]

_SITUATION_PATTERNS: list[tuple[SituationLabel, re.Pattern]] = [
    (
        "probate",
        re.compile(
            r"\b(probate|executor|estate attorney)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "inherited_property",
        re.compile(
            r"\b(inherited|passed away|my mom|my dad)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "preforeclosure",
        re.compile(
            r"\b(foreclosure|notice of default|missed payments)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "divorce",
        re.compile(
            r"\b(divorce|separated)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relocation",
        re.compile(
            r"\b(relocating|moving away|job transfer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tired_landlord",
        re.compile(
            r"\b(bad tenant|rental property|landlord)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "vacant_property",
        re.compile(
            r"\b(vacant|empty|unoccupied)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "downsizing",
        re.compile(
            r"\b(downsizing|retirement|empty nest)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "distressed_seller",
        re.compile(
            r"\b(can't afford|need out|sell fast)\b",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class CallContext:
    seller_name: str | None = None

    current_phase: ConversationPhase = "opening"
    phase_history: list[str] = field(default_factory=list)

    seller_energy: SellerEnergy = "calm"
    energy_history: list[str] = field(default_factory=list)

    situation_label: SituationLabel = "unknown"

    property_issues: list[str] = field(default_factory=list)
    motivation_signals: list[str] = field(default_factory=list)

    last_price_mentioned: int | None = None
    timeline_mentioned: str | None = None

    objections_raised: list[str] = field(default_factory=list)

    disposition: str | None = None

    turn_count: int = 0

    address_known: bool = False
    intent_locked: bool = False

    extended_loaded: bool = False

    def advance_phase(self, target: ConversationPhase) -> bool:
        try:
            current_idx = _PHASE_ORDER.index(self.current_phase)
            target_idx = _PHASE_ORDER.index(target)

        except ValueError:
            return False

        if target_idx > current_idx:
            previous = self.current_phase

            self.phase_history.append(previous)
            self.current_phase = target

            logger.info(
                "conversation_phase advanced from={} to={}",
                previous,
                target,
            )

            return True

        return False

    def get_seller_mode(self) -> str:
        if self.situation_label in ("preforeclosure", "distressed_seller"):
            return "DISTRESSED"

        if self.seller_energy == "rushed":
            return "FAST"

        if self.seller_energy == "motivated":
            return "HOT"

        if self.seller_energy == "skeptical":
            return "SKEPTICAL"

        if self.situation_label in ("inherited_property", "probate"):
            return "INHERITED"

        if self.situation_label == "tired_landlord":
            return "LANDLORD"

        return "STANDARD"

    def get_current_objective(self) -> str:
        if not self.address_known:
            return "GET_ADDRESS"

        if not self.intent_locked:
            return "GET_MOTIVATION"

        if not self.property_issues:
            return "GET_CONDITION"

        if not self.timeline_mentioned:
            return "GET_TIMELINE"

        if self.last_price_mentioned is None:
            return "TEST_PRICE"

        return "BOOK_APPOINTMENT"

    def build_context_prefix(self) -> str:
        parts = [
            f"OBJ={self.get_current_objective()}",
            f"mode={self.get_seller_mode()}",
        ]

        if self.intent_locked:
            parts.append("intent=CONFIRMED")

        if self.address_known:
            parts.append("address=KNOWN")

        if self.situation_label != "unknown":
            parts.append(
                f"situation={self.situation_label.replace('_', ' ')}"
            )

        if self.property_issues:
            parts.append(
                f"issues={', '.join(self.property_issues[-2:])}"
            )

        if self.motivation_signals:
            parts.append(
                f"motivation={', '.join(self.motivation_signals[-2:])}"
            )

        if self.timeline_mentioned:
            parts.append(f"timeline={self.timeline_mentioned}")

        if self.objections_raised:
            parts.append(f"objection={self.objections_raised[-1]}")

        return "[LIVE CONTEXT: " + "; ".join(parts) + "]"


def _extract_price_cents(text: str) -> int | None:
    matches = list(_PRICE_PATTERN.finditer(text))

    if not matches:
        return None

    for match in matches:
        raw = match.group(1).replace(",", "")
        suffix = (match.group(2) or "").lower()

        try:
            val = int(raw)

        except ValueError:
            continue

        if suffix in {"k", "thousand", "grand"}:
            val *= 1000

        elif val < 1000 and "$" not in match.group(0):
            continue

        return val * 100

    return None


class ContextTrackerProcessor(FrameProcessor):
    def __init__(
        self,
        call_ctx: CallContext,
        llm_context=None,
    ):
        super().__init__()

        self._ctx = call_ctx
        self._llm_context = llm_context
        self._last_context_prefix: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()

            if text:
                self._ctx.turn_count += 1

                self._analyze(text)

                await self._maybe_compress_context()

                self._inject_context_prefix()

                logger.info(
                    "context_tracker turn={} phase={} energy={} situation={} "
                    "intent_locked={} address_known={} obj={} text={!r}",
                    self._ctx.turn_count,
                    self._ctx.current_phase,
                    self._ctx.seller_energy,
                    self._ctx.situation_label,
                    self._ctx.intent_locked,
                    self._ctx.address_known,
                    self._ctx.get_current_objective(),
                    text,
                )

        await self.push_frame(frame, direction)

    async def _maybe_compress_context(self) -> None:
        if self._ctx.turn_count < 6:
            return

        if not self._llm_context:
            return

        if not getattr(self._llm_context, "messages", None):
            return

        if len(self._llm_context.messages) <= 10:
            return

        try:
            from backend.voice.context import compress_context

            compressed = await asyncio.to_thread(
                compress_context,
                self._llm_context.messages,
                self._ctx.current_phase,
            )

            self._llm_context.set_messages(compressed)

            logger.info(
                "context_tracker compressed messages count={}",
                len(compressed),
            )

        except Exception as e:
            logger.warning(
                "context_compression_failed error={}",
                str(e),
            )

    def _inject_context_prefix(self) -> None:
        if not self._llm_context:
            return

        if not getattr(self._llm_context, "messages", None):
            return

        prefix = self._ctx.build_context_prefix()

        if prefix == self._last_context_prefix:
            return

        sys_msg = self._llm_context.messages[0]

        content = sys_msg.get("content", "")

        content = re.sub(
            r"\n*\[LIVE CONTEXT:[^\]]*\]\s*",
            "\n",
            content,
        ).rstrip()

        sys_msg["content"] = f"{content}\n\n{prefix}"

        self._last_context_prefix = prefix

        logger.debug(
            "context_tracker injected prefix={}",
            prefix,
        )

    def _analyze(self, text: str) -> None:
        lower = text.lower()

        price = _extract_price_cents(text)

        if price is not None:
            self._ctx.last_price_mentioned = price

        timeline = _TIMELINE_PATTERN.search(lower)

        if timeline:
            self._ctx.timeline_mentioned = timeline.group(0)

        for pattern, label in _ISSUE_PATTERNS:
            if re.search(pattern, lower):
                if label not in self._ctx.property_issues:
                    self._ctx.property_issues.append(label)

        self._ctx.property_issues = self._ctx.property_issues[-6:]

        for pattern, label in _MOTIVATION_PATTERNS:
            if re.search(pattern, lower):
                if label not in self._ctx.motivation_signals:
                    self._ctx.motivation_signals.append(label)

        self._ctx.motivation_signals = self._ctx.motivation_signals[-6:]

        for pattern, label in _OBJECTION_PATTERNS:
            if re.search(pattern, lower):
                if label not in self._ctx.objections_raised:
                    self._ctx.objections_raised.append(label)

        self._ctx.objections_raised = self._ctx.objections_raised[-6:]

        if not self._ctx.intent_locked:
            if any(p in lower for p in _INTENT_PHRASES):
                self._ctx.intent_locked = True

                logger.info(
                    "intent_locked triggered text={!r}",
                    text[:80],
                )

        if not self._ctx.address_known:
            if _ADDRESS_PATTERN.search(text):
                self._ctx.address_known = True

                logger.info(
                    "address_known set text={!r}",
                    text[:80],
                )

        for target_phase, pattern in _PHASE_TRIGGERS:
            if pattern.search(text):
                self._ctx.advance_phase(target_phase)
                break

        self._update_seller_energy(text)
        self._update_situation_label(text)

    def _update_seller_energy(self, text: str) -> None:
        for energy, pattern in _ENERGY_PATTERNS:
            if pattern.search(text):
                if energy != self._ctx.seller_energy:
                    self._ctx.energy_history.append(
                        self._ctx.seller_energy
                    )

                    self._ctx.energy_history = self._ctx.energy_history[-8:]

                    self._ctx.seller_energy = energy

                    logger.debug(
                        "seller_energy changed to={}",
                        energy,
                    )

                return

    def _update_situation_label(self, text: str) -> None:
        if self._ctx.situation_label != "unknown":
            return

        for label, pattern in _SITUATION_PATTERNS:
            if pattern.search(text):
                self._ctx.situation_label = label

                logger.info(
                    "situation_label detected label={}",
                    label,
                )

                return