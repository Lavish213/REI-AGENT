import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Conversation phase — advances forward, never backward
ConversationPhase = Literal[
    "opening", "rapport", "discovery", "pain_extraction",
    "negotiation", "objection_handling", "close_attempt", "wrap_up",
]

_PHASE_ORDER = [
    "opening", "rapport", "discovery", "pain_extraction",
    "negotiation", "objection_handling", "close_attempt", "wrap_up",
]

# Seller energy state — can shift freely
SellerEnergy = Literal[
    "calm", "emotional", "skeptical", "rushed", "talkative", "hesitant", "motivated",
]

# Situation labels — detected from speech
SituationLabel = Literal[
    "inherited_property", "tired_landlord", "probate", "preforeclosure",
    "relocation", "divorce", "downsizing", "vacant_property", "distressed_seller",
    "unknown",
]


@dataclass
class CallContext:
    seller_name: str | None = None
    opener_used: str | None = None
    last_opener_used: str | None = None
    # Phase tracker (G15)
    current_phase: ConversationPhase = "opening"
    phase_history: list[str] = field(default_factory=list)
    # Seller energy (G16)
    seller_energy: SellerEnergy = "calm"
    energy_history: list[str] = field(default_factory=list)
    # Situation label (G22)
    situation_label: SituationLabel = "unknown"
    # Original fields
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
        """Advance to target phase only if it's forward in the arc."""
        try:
            current_idx = _PHASE_ORDER.index(self.current_phase)
            target_idx = _PHASE_ORDER.index(target)
        except ValueError:
            return False
        if target_idx > current_idx:
            self.phase_history.append(self.current_phase)
            self.current_phase = target
            logger.info("conversation_phase advanced from={} to={}", self.phase_history[-1], target)
            return True
        return False

    def build_context_prefix(self) -> str:
        parts = []
        if self.seller_name:
            parts.append(f"seller name: {self.seller_name}")
        parts.append(f"phase: {self.current_phase}")
        parts.append(f"energy: {self.seller_energy}")
        if self.situation_label != "unknown":
            parts.append(f"situation: {self.situation_label.replace('_', ' ')}")
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

# ── Phase transition triggers ──────────────────────────────────────────────────
# Keyed by target phase — first match wins
_PHASE_TRIGGERS: list[tuple[str, re.Pattern]] = [
    ("rapport", re.compile(
        r"\b(my name is|call me|i'm [a-z]+|yes (that's|that is)|ha(ha)?|funny|nice|good to (hear|talk))\b",
        re.IGNORECASE,
    )),
    ("discovery", re.compile(
        r"\b(roof|foundation|plumbing|hvac|inherited|landlord|behind on|repairs|condition|tenant|vacant)\b",
        re.IGNORECASE,
    )),
    ("pain_extraction", re.compile(
        r"\b(stressed|overwhelmed|need to get out|can't afford|losing sleep|desperate|struggling|honest(ly)?|look,|i mean,)\b",
        re.IGNORECASE,
    )),
    ("negotiation", re.compile(
        r"\$\s*\d|\bhow much|what('s| is) (it|your offer|the offer)|make me an offer|what (are you|would you) (paying|offer)\b",
        re.IGNORECASE,
    )),
    ("objection_handling", re.compile(
        r"\b(too low|think about|need time|talk to|not ready|someone else|another offer|going to list|realtor)\b",
        re.IGNORECASE,
    )),
    ("close_attempt", re.compile(
        r"\b(walk(through| through)|come see|meet|appointment|when can|schedule|set up|come over|visit)\b",
        re.IGNORECASE,
    )),
    ("wrap_up", re.compile(
        r"\b(thanks? (for calling|sophia)|bye|goodbye|have a (good|great)|talk (later|soon)|take care)\b",
        re.IGNORECASE,
    )),
]

# ── Seller energy detection ────────────────────────────────────────────────────
_ENERGY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("rushed", re.compile(
        r"\b(gotta go|in a hurry|quick(ly)?|make it fast|don't have (much |a lot of )?time|busy)\b",
        re.IGNORECASE,
    )),
    ("emotional", re.compile(
        r"\b(honestly|look[, ]|i mean[, ]|this is (hard|tough|stressful)|i('m| am) (stressed|worried|scared|upset)|i don't know what to do)\b",
        re.IGNORECASE,
    )),
    ("skeptical", re.compile(
        r"\b(i don't know|not sure|maybe|seems like|sounds (like|too good)|how do i know|is this (legit|real|a scam))\b",
        re.IGNORECASE,
    )),
    ("motivated", re.compile(
        r"\b(definitely|absolutely|yes|when can|let's do it|i('m| am) ready|sounds good|let's move forward|i want to)\b",
        re.IGNORECASE,
    )),
    ("hesitant", re.compile(
        r"\b(well[, ]|um[, ]|uh[, ]|i guess|i think maybe|not sure (if|about)|haven't (decided|thought))\b",
        re.IGNORECASE,
    )),
]

# ── Situation label detection ──────────────────────────────────────────────────
_SITUATION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("inherited_property", re.compile(
        r"\b(inherited|estate|passed away|died|my (mom|dad|parent|grandma|grandpa|uncle|aunt)|probate)\b",
        re.IGNORECASE,
    )),
    ("probate", re.compile(
        r"\b(probate|estate attorney|executor|administrator|intestate)\b",
        re.IGNORECASE,
    )),
    ("preforeclosure", re.compile(
        r"\b(foreclosure|behind on (the )?mortgage|notice of default|NOD|missed (payment|payments)|can't (pay|afford) (the )?mortgage)\b",
        re.IGNORECASE,
    )),
    ("divorce", re.compile(
        r"\b(divorce|divorcing|separated|splitting up|ex-(wife|husband|spouse)|going through a divorce)\b",
        re.IGNORECASE,
    )),
    ("relocation", re.compile(
        r"\b(relocating|moving (to|out of state|away)|job (transfer|relocation)|company (relocated|moved))\b",
        re.IGNORECASE,
    )),
    ("tired_landlord", re.compile(
        r"\b(tired (of )?landlord|bad tenant|eviction|rental property|renters|don't want to (be a|deal with) landlord)\b",
        re.IGNORECASE,
    )),
    ("vacant_property", re.compile(
        r"\b(vacant|empty|nobody (living|lives) there|sitting empty|been empty|unoccupied)\b",
        re.IGNORECASE,
    )),
    ("downsizing", re.compile(
        r"\b(downsize|downsizing|too big (for us|for me|now)|kids (moved out|are gone)|empty nest|retirement)\b",
        re.IGNORECASE,
    )),
    ("distressed_seller", re.compile(
        r"\b(can't (afford|keep|maintain)|falling apart|overwhelming|too much to handle|need (out|to sell fast))\b",
        re.IGNORECASE,
    )),
]


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
                    compressed = await asyncio.to_thread(
                        compress_context,
                        self._llm_context.messages,
                        self._ctx.current_phase,
                    )
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

        # Phase transition (G15)
        for target_phase, pattern in _PHASE_TRIGGERS:
            if pattern.search(text):
                self._ctx.advance_phase(target_phase)  # type: ignore[arg-type]
                break

        # Seller energy (G16) — use word count as talkative proxy
        word_count = len(text.split())
        if word_count > 40:
            new_energy = "talkative"
        else:
            new_energy = None
            for energy, pattern in _ENERGY_PATTERNS:
                if pattern.search(text):
                    new_energy = energy
                    break

        if new_energy and new_energy != self._ctx.seller_energy:
            self._ctx.energy_history.append(self._ctx.seller_energy)
            if len(self._ctx.energy_history) > 10:
                self._ctx.energy_history = self._ctx.energy_history[-10:]
            self._ctx.seller_energy = new_energy  # type: ignore[assignment]
            logger.debug("seller_energy changed to={}", new_energy)

        # Situation label (G22) — first detected wins
        if self._ctx.situation_label == "unknown":
            for label, pattern in _SITUATION_PATTERNS:
                if pattern.search(text):
                    self._ctx.situation_label = label  # type: ignore[assignment]
                    logger.info("situation_label detected label={}", label)
                    break
