from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frame_processor import FrameProcessor


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
    "moving to",
    "we're moving",
    "i'm moving",
    "relocating to",
    "relocating",
    "moving away",
    "gotta sell",
    "need to get out",
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
    (r"\b(need to move|want to move|need the cash|need cash|gotta move|trying to move)\b", "urgent"),
    (r"\b(divorce|divorcing)\b", "divorce"),
    (r"\b(foreclosure|behind on|auction)\b", "foreclosure"),
    (r"\b(inherited|estate|probate|passed away)\b", "inheritance"),
    (r"\b(relocating|moving|job transfer)\b", "relocation"),
    (r"\b(moving to|relocating to|we're moving|i'm moving)\b", "relocation"),
    (r"\b(bad tenant|tenant|renter)\b", "landlord"),
]

_OBJECTION_PATTERNS = [
    (r"\b(too low|worth more|higher offer)\b", "price"),
    (r"\b(agent|realtor|listing|mls)\b", "mls"),
    (r"\b(think about it|need time|not ready)\b", "hesitation"),
    (r"\b(other offer|another buyer)\b", "competition"),
    (r"\b(not interested|stop calling)\b", "not_interested"),
]

_AGENT_PATTERN = re.compile(
    r"\b(agent|realtor|listed|listing|on the market|with an agent)\b",
    re.IGNORECASE,
)

_MORTGAGE_HIGH_PATTERN = re.compile(
    r"\b(mortgage|still owe|loan|paying on it|bank)\b",
    re.IGNORECASE,
)

_FREE_CLEAR_PATTERN = re.compile(
    r"\b(free and clear|no mortgage|paid off|own it outright|no loan)\b",
    re.IGNORECASE,
)

_ENERGY_PATTERNS: list[tuple[SellerEnergy, re.Pattern]] = [
    ("rushed", re.compile(r"\b(gotta go|busy|quick|in a hurry)\b", re.IGNORECASE)),
    ("skeptical", re.compile(r"\b(not sure|sounds too good|is this legit|scam)\b", re.IGNORECASE)),
    ("motivated", re.compile(r"\b(i'm ready|sounds good|let's do it|definitely)\b", re.IGNORECASE)),
    ("hesitant", re.compile(r"\b(maybe|i guess|not sure if)\b", re.IGNORECASE)),
]

_SITUATION_PATTERNS: list[tuple[SituationLabel, re.Pattern]] = [
    ("probate", re.compile(r"\b(probate|executor|estate attorney)\b", re.IGNORECASE)),
    ("inherited_property", re.compile(r"\b(inherited|passed away|my mom|my dad)\b", re.IGNORECASE)),
    ("preforeclosure", re.compile(r"\b(foreclosure|notice of default|missed payments)\b", re.IGNORECASE)),
    ("divorce", re.compile(r"\b(divorce|separated)\b", re.IGNORECASE)),
    ("relocation", re.compile(r"\b(relocating|moving away|job transfer)\b", re.IGNORECASE)),
    ("tired_landlord", re.compile(r"\b(bad tenant|rental property|landlord)\b", re.IGNORECASE)),
    ("vacant_property", re.compile(r"\b(vacant|empty|unoccupied)\b", re.IGNORECASE)),
    ("downsizing", re.compile(r"\b(downsizing|retirement|empty nest)\b", re.IGNORECASE)),
    ("distressed_seller", re.compile(r"\b(can't afford|need out|sell fast)\b", re.IGNORECASE)),
]


@dataclass(slots=True)
class CallContext:
    seller_name: str | None = None
    seller_energy: SellerEnergy = "calm"
    energy_history: list[str] = field(default_factory=list)
    situation_label: SituationLabel = "unknown"
    property_issues: list[str] = field(default_factory=list)
    motivation_signals: list[str] = field(default_factory=list)
    objections_raised: list[str] = field(default_factory=list)
    last_price_mentioned: int | None = None
    timeline_mentioned: str | None = None
    disposition: str | None = None
    turn_count: int = 0
    address_known: bool = False
    intent_locked: bool = False
    extended_loaded: bool = False

    has_agent: bool = False
    mortgage_status: str = "unknown"
    free_and_clear: bool = False
    price_resistance: bool = False

    objective: str = "GET_MOTIVATION"
    runtime_instruction: str | None = None

    emotional_state: str = "NEUTRAL"
    emotional_intensity: float = 0.0
    trust_score: float = 5.0
    resistance_level: str = "NONE"
    resistance_softening: bool = False
    momentum_score: float = 5.0
    momentum_direction: str = "STABLE"
    deal_heat: float = 0.0
    deal_heat_level: str = "COLD"
    fatigue_level: str = "FRESH"
    microstate: str = "NEUTRAL"
    microstate_duration: int = 1
    comm_style: str = "STANDARD"
    financial_pressure: str = "NONE"
    seller_sophistication: str = "AVERAGE"
    consecutive_silences: int = 0
    call_should_end: bool = False
    last_sophia_words: int = 0
    tts_speed: float = 0.85
    tts_volume: float = 0.85

    def get_seller_mode(self) -> str:
        if self.emotional_state in {"DISTRESSED", "GRIEVING"}:
            return "DISTRESSED"
        if self.situation_label in {"preforeclosure", "distressed_seller"}:
            return "DISTRESSED"
        if self.seller_energy == "rushed":
            return "FAST"
        if self.seller_energy == "motivated" or self.deal_heat >= 7.0:
            return "HOT"
        if self.seller_energy == "skeptical" or self.trust_score < 4.0:
            return "SKEPTICAL"
        if self.situation_label in {"inherited_property", "probate"}:
            return "INHERITED"
        if self.situation_label == "tired_landlord":
            return "LANDLORD"
        return "STANDARD"

    def build_context_prefix(self) -> str:
        addr = 1 if self.address_known else 0
        intent = 1 if self.intent_locked else 0
        obj = self.objective
        mode = self.get_seller_mode()

        tag = f"[CTX:OBJ={obj}|MODE={mode}|ADDR={addr}|INTENT={intent}]"

        if self.objections_raised:
            tag = tag[:-1] + f"|OBJ_LAST={self.objections_raised[-1]}]"

        if self.runtime_instruction:
            tag += f"\n[RUNTIME: {self.runtime_instruction}]"
            self.runtime_instruction = None

        return tag


def _extract_price_cents(text: str) -> int | None:
    matches = list(_PRICE_PATTERN.finditer(text))
    if not matches:
        return None

    for match in matches:
        raw = match.group(1).replace(",", "")
        suffix = (match.group(2) or "").lower()

        try:
            value = int(raw)
        except ValueError:
            continue

        if suffix in {"k", "thousand", "grand"}:
            value *= 1000
        elif value < 1000 and "$" not in match.group(0):
            continue

        return value * 100

    return None


class ContextTrackerProcessor(FrameProcessor):
    def __init__(self, call_ctx: CallContext, llm_context=None):
        super().__init__()
        self._ctx = call_ctx
        self._llm_context = llm_context
        self._last_context_prefix: str | None = None
        self._objective_engine = None

    def set_objective_engine(self, engine) -> None:
        self._objective_engine = engine

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()

            if text:
                self._ctx.turn_count += 1
                self._analyze(text)

                if self._objective_engine is not None:
                    self._ctx.objective = self._objective_engine.decide(self._ctx)

                await self._maybe_compress_context()
                self._inject_context_prefix()

                logger.info(
                    "context_tracker turn={} energy={} situation={} "
                    "obj={} mode={} addr={} intent={} "
                    "trust={:.1f} heat={:.1f} resistance={} "
                    "microstate={} fatigue={} text={!r}",
                    self._ctx.turn_count,
                    self._ctx.seller_energy,
                    self._ctx.situation_label,
                    self._ctx.objective,
                    self._ctx.get_seller_mode(),
                    self._ctx.address_known,
                    self._ctx.intent_locked,
                    self._ctx.trust_score,
                    self._ctx.deal_heat,
                    self._ctx.resistance_level,
                    self._ctx.microstate,
                    self._ctx.fatigue_level,
                    text,
                )

        await self.push_frame(frame, direction)

    async def _maybe_compress_context(self) -> None:
        if self._ctx.turn_count < 10:
            return
        if not self._llm_context:
            return
        if not getattr(self._llm_context, "messages", None):
            return
        if len(self._llm_context.messages) <= 16:
            return

        try:
            from backend.voice.context import compress_context
            compressed = await asyncio.to_thread(
                compress_context,
                self._llm_context.messages,
                self._ctx.objective,
            )
            self._llm_context.set_messages(compressed)
            logger.info("context compressed messages={}", len(compressed))
        except Exception as error:
            logger.warning("context compression failed error={}", str(error))

    def _inject_context_prefix(self) -> None:
        if not self._llm_context:
            return
        messages = getattr(self._llm_context, "messages", None)
        if not messages:
            return

        prefix = self._ctx.build_context_prefix()

        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        if not last_user:
            return

        content = last_user.get("content", "")
        if isinstance(content, str):
            content = re.sub(r"\[CTX:[^\]]*\]\s*", "", content).strip()
            content = re.sub(r"\[RUNTIME:[^\]]*\]\s*", "", content).strip()
            last_user["content"] = f"{prefix}\n{content}"
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = re.sub(r"\[CTX:[^\]]*\]\s*", "", block["text"]).strip()
                    block["text"] = re.sub(r"\[RUNTIME:[^\]]*\]\s*", "", block["text"]).strip()
                    block["text"] = f"{prefix}\n{block['text']}"
                    break

        self._last_context_prefix = prefix
        logger.debug("context prefix updated prefix={}", prefix)

    def _analyze(self, text: str) -> None:
        lower = text.lower()

        price = _extract_price_cents(text)
        if price is not None:
            self._ctx.last_price_mentioned = price

        timeline_match = _TIMELINE_PATTERN.search(lower)
        if timeline_match:
            self._ctx.timeline_mentioned = timeline_match.group(0)

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

        if not self._ctx.intent_locked and any(phrase in lower for phrase in _INTENT_PHRASES):
            self._ctx.intent_locked = True
            logger.info("seller intent locked")

        if not self._ctx.address_known and _ADDRESS_PATTERN.search(text):
            self._ctx.address_known = True
            logger.info("property address detected")

        if not self._ctx.has_agent and _AGENT_PATTERN.search(text):
            self._ctx.has_agent = True
            logger.info("agent detected")

        if self._ctx.mortgage_status == "unknown":
            if _FREE_CLEAR_PATTERN.search(text):
                self._ctx.free_and_clear = True
                self._ctx.mortgage_status = "clear"
                logger.info("free and clear detected")
            elif _MORTGAGE_HIGH_PATTERN.search(text):
                self._ctx.mortgage_status = "has_mortgage"
                logger.info("mortgage detected")

        self._update_seller_energy(text)
        self._update_situation_label(text)

    def _update_seller_energy(self, text: str) -> None:
        for energy, pattern in _ENERGY_PATTERNS:
            if pattern.search(text):
                if energy == self._ctx.seller_energy:
                    return
                self._ctx.energy_history.append(self._ctx.seller_energy)
                self._ctx.energy_history = self._ctx.energy_history[-8:]
                self._ctx.seller_energy = energy
                logger.debug("seller energy updated energy={}", energy)
                return

    def _update_situation_label(self, text: str) -> None:
        if self._ctx.situation_label != "unknown":
            return
        for label, pattern in _SITUATION_PATTERNS:
            if pattern.search(text):
                self._ctx.situation_label = label
                logger.info("seller situation detected label={}", label)
                return