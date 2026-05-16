import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


ConversationPhase = Literal[
    "opening",
    "rapport",
    "discovery",
    "pain_extraction",
    "negotiation",
    "objection_handling",
    "close_attempt",
    "wrap_up",
]

_PHASE_ORDER = [
    "opening",
    "rapport",
    "discovery",
    "pain_extraction",
    "negotiation",
    "objection_handling",
    "close_attempt",
    "wrap_up",
]

SellerEnergy = Literal[
    "calm",
    "emotional",
    "skeptical",
    "rushed",
    "talkative",
    "hesitant",
    "motivated",
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


@dataclass
class CallContext:
    seller_name: str | None = None
    opener_used: str | None = None
    last_opener_used: str | None = None

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
            logger.info("conversation_phase advanced from={} to={}", previous, target)
            return True

        return False

    def build_context_prefix(self) -> str:
        parts = [
            f"phase={self.current_phase}",
            f"energy={self.seller_energy}",
        ]

        if self.situation_label != "unknown":
            parts.append(f"situation={self.situation_label.replace('_', ' ')}")

        if self.property_issues:
            parts.append(f"issues={', '.join(self.property_issues[-2:])}")

        if self.motivation_signals:
            parts.append(f"motivation={', '.join(self.motivation_signals[-2:])}")

        if self.last_price_mentioned is not None:
            dollar = self.last_price_mentioned // 100
            parts.append(f"price mentioned=${dollar:,}")

        if self.timeline_mentioned:
            parts.append(f"timeline={self.timeline_mentioned}")

        if self.objections_raised:
            parts.append(f"objection={self.objections_raised[-1]}")

        if self.disposition:
            parts.append(f"disposition={self.disposition}")

        return "[LIVE CONTEXT: " + "; ".join(parts) + "]"


_ISSUE_PATTERNS = [
    (r"\b(roof|roofing|leak|leaking)\b", "roof problem"),
    (r"\b(foundation|crack|settling)\b", "foundation issue"),
    (r"\b(plumbing|pipes|water damage)\b", "plumbing issue"),
    (r"\b(hvac|a/c|ac|heat|furnace|air conditioning)\b", "HVAC issue"),
    (r"\b(mold|mildew|asbestos)\b", "environmental issue"),
    (r"\b(fire damage|flood|water damage)\b", "damage"),
    (r"\b(hoard|hoarding|junk|trash|mess)\b", "condition issue"),
]

_MOTIVATION_PATTERNS = [
    (r"\b(need to sell|have to sell|must sell|sell fast|sell quickly|asap)\b", "urgent to sell"),
    (r"\b(divorce|divorcing|separated|splitting)\b", "divorce"),
    (r"\b(foreclosure|behind on|missed payment|default|auction)\b", "foreclosure risk"),
    (r"\b(inherited|estate|probate|passed away|died)\b", "inherited property"),
    (r"\b(relocating|moving|transfer|job)\b", "relocation"),
    (r"\b(tired landlord|bad tenant|eviction|renter|tenant)\b", "landlord tired"),
    (r"\b(behind on taxes|tax lien|irs)\b", "tax issues"),
]

_OBJECTION_PATTERNS = [
    (r"\b(too low|not enough|worth more|higher offer)\b", "price too low"),
    (r"\b(agent|realtor|listing|mls|on the market)\b", "considering MLS"),
    (r"\b(think about it|need time|not ready|talk to my|talk with my)\b", "needs time"),
    (r"\b(other offer|someone else|another buyer)\b", "competing offer"),
    (r"\b(not interested|stop calling|take me off|do not call)\b", "not interested"),
]

_EXTENDED_PROCESS_PATTERN = re.compile(
    r"\b("
    r"how does (this|it) work|title company|escrow|what do i sign|"
    r"how.?do i get paid|is this legal|purchase agreement|"
    r"what happens (when|after|at)|who pays closing|closing costs"
    r")\b",
    re.IGNORECASE,
)

_EXTENDED_LOCATION_PATTERN = re.compile(
    r"\b("
    r"south stockton|north stockton|weston ranch|lincoln village|"
    r"march lane|hammer lane|flood zone|delta|lincoln unified|"
    r"spanos|valley oak|brookside|lodi|tracy|manteca|modesto"
    r")\b",
    re.IGNORECASE,
)

_EXTENDED_SPANISH_PATTERN = re.compile(
    r"\b("
    r"hola|oye|buenos|buenas|espa[nñ]ol|hablas|habla|"
    r"[oó]rale|sale|neta|ahorita|qu[eé] onda|[aá]ndale"
    r")\b",
    re.IGNORECASE,
)

_EXTENDED_SUBJECTTO_PATTERN = re.compile(
    r"\b("
    r"owe (too much|more than|a lot)|upside down|subject.?to|"
    r"behind on (the )?mortgage|negative equity|underwater|not much equity"
    r")\b",
    re.IGNORECASE,
)

_EXTENDED_PROPERTY_PATTERN = re.compile(
    r"\b("
    r"solar|hoa|homeowners.?association|tenant|renter|lease|"
    r"prop 13|proposition 13|property tax|transfer tax"
    r")\b",
    re.IGNORECASE,
)

_TIMELINE_PATTERN = re.compile(
    r"\b("
    r"asap|immediately|right away|today|tomorrow|next week|next month|"
    r"30 days|60 days|90 days|few months|end of the year|this week"
    r")\b",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(
    r"(?:\$?\s*(\d{2,3}(?:,\d{3})+|\d{2,6})\s*(k|thousand|grand)?)",
    re.IGNORECASE,
)

_PHASE_TRIGGERS: list[tuple[ConversationPhase, re.Pattern]] = [
    (
        "rapport",
        re.compile(
            r"\b(my name is|call me|i'm [a-z]+|yes that's|yeah that's|haha|funny|nice)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "discovery",
        re.compile(
            r"\b(roof|foundation|plumbing|hvac|inherited|landlord|behind on|repairs|condition|tenant|vacant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "pain_extraction",
        re.compile(
            r"\b(stressed|overwhelmed|need to get out|can't afford|desperate|struggling|hard|tough)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "negotiation",
        re.compile(
            r"\$\s*\d|\bhow much|what('s| is) (it|your offer|the offer)|make me an offer|what would you pay\b",
            re.IGNORECASE,
        ),
    ),
    (
        "objection_handling",
        re.compile(
            r"\b(too low|think about|need time|not ready|someone else|another offer|list|realtor|agent|not interested)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "close_attempt",
        re.compile(
            r"\b(walkthrough|walk through|come see|meet|appointment|schedule|set up|come over|visit)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "wrap_up",
        re.compile(
            r"\b(bye|goodbye|talk later|talk soon|take care|have a good|have a great|thanks sophia)\b",
            re.IGNORECASE,
        ),
    ),
]

_ENERGY_PATTERNS: list[tuple[SellerEnergy, re.Pattern]] = [
    (
        "rushed",
        re.compile(
            r"\b(gotta go|in a hurry|make it fast|don't have time|busy|quick)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "emotional",
        re.compile(
            r"\b(honestly|this is hard|this is tough|stressful|stressed|worried|scared|upset|don't know what to do)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "skeptical",
        re.compile(
            r"\b(i don't know|not sure|seems like|sounds too good|how do i know|is this legit|is this real|scam)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "motivated",
        re.compile(
            r"\b(definitely|yes|when can|let's do it|i'm ready|sounds good|move forward|i want to sell)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hesitant",
        re.compile(
            r"\b(well|um|uh|i guess|maybe|not sure if|haven't decided|haven't thought)\b",
            re.IGNORECASE,
        ),
    ),
]

_SITUATION_PATTERNS: list[tuple[SituationLabel, re.Pattern]] = [
    (
        "probate",
        re.compile(
            r"\b(probate|estate attorney|executor|administrator|intestate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "inherited_property",
        re.compile(
            r"\b(inherited|estate|passed away|died|my mom|my dad|my parent|my grandma|my grandpa|my uncle|my aunt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "preforeclosure",
        re.compile(
            r"\b(foreclosure|behind on (the )?mortgage|notice of default|NOD|missed payments?|can't afford the mortgage|auction)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "divorce",
        re.compile(
            r"\b(divorce|divorcing|separated|splitting up|ex-wife|ex-husband|ex-spouse)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relocation",
        re.compile(
            r"\b(relocating|moving away|moving out of state|job transfer|company relocated)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tired_landlord",
        re.compile(
            r"\b(tired landlord|bad tenant|eviction|rental property|renters|landlord)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "vacant_property",
        re.compile(
            r"\b(vacant|empty|nobody living there|sitting empty|been empty|unoccupied)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "downsizing",
        re.compile(
            r"\b(downsize|downsizing|too big|kids moved out|kids are gone|empty nest|retirement)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "distressed_seller",
        re.compile(
            r"\b(can't afford|can't keep|can't maintain|falling apart|too much to handle|need out|sell fast)\b",
            re.IGNORECASE,
        ),
    ),
]


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


def _load_extended_prompt(extended_path: str) -> str:
    try:
        with open(extended_path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.warning("extended_prompt_load_failed path={} error={}", extended_path, str(e))
        return ""


def _shrink_extended_prompt(content: str, max_chars: int = 5000) -> str:
    content = content.strip()

    if len(content) <= max_chars:
        return content

    trimmed = content[:max_chars].rsplit("\n", 1)[0].strip()

    return (
        trimmed
        + "\n\nNOTE: Extended context was trimmed for realtime voice latency. "
        "Use only the most relevant guidance."
    )


class ContextTrackerProcessor(FrameProcessor):
    def __init__(
        self,
        call_ctx: CallContext,
        llm_context=None,
        extended_prompt_path: str | None = None,
    ):
        super().__init__()
        self._ctx = call_ctx
        self._llm_context = llm_context
        self._extended_prompt_path = extended_prompt_path
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
                    "context_tracker turn={} phase={} energy={} situation={} text={!r}",
                    self._ctx.turn_count,
                    self._ctx.current_phase,
                    self._ctx.seller_energy,
                    self._ctx.situation_label,
                    text,
                )

        await self.push_frame(frame, direction)

    async def _maybe_compress_context(self) -> None:
        if self._ctx.turn_count < 8:
            return

        if not self._llm_context:
            return

        if not getattr(self._llm_context, "messages", None):
            return

        if len(self._llm_context.messages) <= 8:
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
            logger.warning("context_compression_failed error={}", str(e))

    def _inject_context_prefix(self) -> None:
        if not self._llm_context or not getattr(self._llm_context, "messages", None):
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

        logger.debug("context_tracker injected prefix={}", prefix)

    def _maybe_load_extended(self, text: str) -> None:
        if self._ctx.extended_loaded:
            return

        if not self._llm_context or not self._extended_prompt_path:
            return

        triggered = (
            _EXTENDED_PROCESS_PATTERN.search(text)
            or _EXTENDED_LOCATION_PATTERN.search(text)
            or _EXTENDED_SPANISH_PATTERN.search(text)
            or _EXTENDED_SUBJECTTO_PATTERN.search(text)
            or _EXTENDED_PROPERTY_PATTERN.search(text)
        )

        if not triggered:
            return

        content = _load_extended_prompt(self._extended_prompt_path)

        if not content or not getattr(self._llm_context, "messages", None):
            return

        content = _shrink_extended_prompt(content)

        self._llm_context.messages[0]["content"] += f"\n\n{content}"
        self._ctx.extended_loaded = True

        logger.info("extended_prompt_loaded trigger_text={}", text[:80])

    def _analyze(self, text: str) -> None:
        lower = text.lower()

        self._maybe_load_extended(text)

        price = _extract_price_cents(text)
        if price is not None:
            self._ctx.last_price_mentioned = price

        timeline = _TIMELINE_PATTERN.search(lower)
        if timeline:
            self._ctx.timeline_mentioned = timeline.group(0)

        for pattern, label in _ISSUE_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.property_issues:
                self._ctx.property_issues.append(label)
                self._ctx.property_issues = self._ctx.property_issues[-8:]

        for pattern, label in _MOTIVATION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.motivation_signals:
                self._ctx.motivation_signals.append(label)
                self._ctx.motivation_signals = self._ctx.motivation_signals[-8:]

        for pattern, label in _OBJECTION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.objections_raised:
                self._ctx.objections_raised.append(label)
                self._ctx.objections_raised = self._ctx.objections_raised[-8:]

        for target_phase, pattern in _PHASE_TRIGGERS:
            if pattern.search(text):
                self._ctx.advance_phase(target_phase)
                break

        self._update_seller_energy(text)
        self._update_situation_label(text)

    def _update_seller_energy(self, text: str) -> None:
        word_count = len(text.split())

        new_energy: SellerEnergy | None = None

        if word_count > 45:
            new_energy = "talkative"
        else:
            for energy, pattern in _ENERGY_PATTERNS:
                if pattern.search(text):
                    new_energy = energy
                    break

        if not new_energy or new_energy == self._ctx.seller_energy:
            return

        self._ctx.energy_history.append(self._ctx.seller_energy)
        self._ctx.energy_history = self._ctx.energy_history[-10:]
        self._ctx.seller_energy = new_energy

        logger.debug("seller_energy changed to={}", new_energy)

    def _update_situation_label(self, text: str) -> None:
        if self._ctx.situation_label != "unknown":
            return

        for label, pattern in _SITUATION_PATTERNS:
            if pattern.search(text):
                self._ctx.situation_label = label
                logger.info("situation_label detected label={}", label)
                return