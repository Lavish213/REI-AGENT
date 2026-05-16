import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CallContext — runtime acquisition state
# ---------------------------------------------------------------------------

@dataclass
class CallContext:
    # Identity
    seller_name: str | None = None
    opener_used: str | None = None
    last_opener_used: str | None = None

    # Conversation phase (legacy — still tracked for QA/observability)
    current_phase: ConversationPhase = "opening"
    phase_history: list[str] = field(default_factory=list)

    # Seller signals
    seller_energy: SellerEnergy = "calm"
    energy_history: list[str] = field(default_factory=list)
    situation_label: SituationLabel = "unknown"

    # Acquisition field tracking — binary flags set once confirmed
    intent_confirmed: bool = False   # seller stated they want to sell
    address_known: bool = False      # we have property address (from preloader or confirmed)
    occupancy_known: bool = False    # living there / renting / vacant
    condition_known: bool = False    # move-in ready / needs work / rough
    motivation_known: bool = False   # divorce / foreclosure / relocation / etc.
    timeline_known: bool = False     # how soon they want to close
    price_expectation_known: bool = False  # what they need to walk away with

    # Raw signal data
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

    # ------------------------------------------------------------------
    # Momentum / pacing state (Batch 3)
    # ------------------------------------------------------------------

    # pacing_state drives sentence count limits in SpokenRendererProcessor
    # "warm" → 3 sentences max (early call, opener)
    # "operational" → 2 sentences max (intent confirmed, gathering facts)
    # "tight" → 1 sentence max (late stage, hot lead, fast qualification)
    pacing_state: str = "warm"

    # silence_hint consumed once by SpokenRendererProcessor to inject pause
    # set by _analyze() after price/emotional/skeptical signals
    silence_hint: str | None = None

    # ------------------------------------------------------------------
    # Redirect state (Batch 4)
    # ------------------------------------------------------------------

    # redirect_needed consumed once by SpokenRendererProcessor
    # set when seller is rambling (talkative) and call is past opening
    redirect_needed: bool = False

    # ------------------------------------------------------------------
    # Objective engine
    # ------------------------------------------------------------------

    def get_current_objective(self) -> str:
        """Return the highest-priority missing acquisition field."""
        if not self.intent_confirmed:
            return "CONFIRM_INTENT"
        if not self.address_known:
            return "GET_ADDRESS"
        if not self.motivation_known:
            return "GET_MOTIVATION"
        if not self.occupancy_known:
            return "GET_OCCUPANCY"
        if not self.condition_known:
            return "GET_CONDITION"
        if not self.timeline_known:
            return "GET_TIMELINE"
        if not self.price_expectation_known:
            return "TEST_PRICE"
        return "BOOK_APPOINTMENT"

    def get_forbidden_moves(self) -> list[str]:
        """Return list of questions that are illegal this turn (fact already known)."""
        forbidden = []
        if self.intent_confirmed:
            forbidden.append("ask if they want to sell")
        if self.address_known:
            forbidden.append("ask for address")
        if self.occupancy_known:
            forbidden.append("ask if they live there or if it is vacant")
        if self.motivation_known:
            forbidden.append("ask why they want to sell")
        if self.condition_known:
            forbidden.append("ask about condition")
        if self.timeline_known:
            forbidden.append("ask about timeline")
        return forbidden

    def get_seller_mode(self) -> str:
        """Map situation + energy to a behavioral mode label."""
        if self.seller_energy == "rushed":
            return "FAST"
        if self.situation_label in ("preforeclosure", "distressed_seller"):
            return "DISTRESSED"
        if self.situation_label == "tired_landlord":
            return "LANDLORD"
        if self.situation_label in ("inherited_property", "probate"):
            return "INHERITED"
        if self.situation_label == "divorce":
            return "DIVORCE"
        if self.seller_energy == "skeptical":
            return "SKEPTICAL"
        if self.seller_energy == "emotional":
            return "EMOTIONAL"
        if self.seller_energy == "motivated" or self.disposition == "HOT":
            return "HOT"
        return "STANDARD"

    # ------------------------------------------------------------------
    # Context prefix (injected into system message every turn)
    # ------------------------------------------------------------------

    def build_context_prefix(self) -> str:
        from backend.voice.phrases import PIVOT_BANK

        objective = self.get_current_objective()
        forbidden = self.get_forbidden_moves()
        seller_mode = self.get_seller_mode()

        parts = [f"OBJ={objective}"]

        # Inject preferred phrases for this objective — LLM should use these exactly
        preferred = PIVOT_BANK.get(objective, [])
        if preferred:
            parts.append("SAY=" + " / ".join(f'"{p}"' for p in preferred[:2]))

        if forbidden:
            parts.append("NO=" + "; ".join(forbidden))

        if seller_mode != "STANDARD":
            parts.append(f"mode={seller_mode}")

        if self.timeline_mentioned:
            parts.append(f"timeline={self.timeline_mentioned}")

        if self.last_price_mentioned is not None:
            parts.append(f"price=${self.last_price_mentioned // 100:,}")

        if self.objections_raised:
            parts.append(f"objection={self.objections_raised[-1]}")

        if self.situation_label != "unknown":
            parts.append(f"situation={self.situation_label.replace('_', ' ')}")

        return "[LIVE CONTEXT: " + "; ".join(parts) + "]"

    # ------------------------------------------------------------------
    # Phase management (legacy — kept for QA observability)
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

_INTENT_CONFIRMED_PATTERN = re.compile(
    r"\b("
    r"want(s)? to sell|trying to sell|need(s)? to sell|looking to sell|"
    r"thinking (about|of) sell(ing)?|ready to sell|interested in sell(ing)?|"
    r"going to sell|planning to sell|"
    r"sell(ing)? (my|the|this) (house|home|place|property)|"
    r"yeah.{0,15}sell|yes.{0,15}sell|"
    r"put it on the market|list(ing)? it|get rid of it|unload it"
    r")\b",
    re.IGNORECASE,
)

_OCCUPANCY_PATTERN = re.compile(
    r"\b("
    r"living there|i live there|we live there|owner.?occupied|"
    r"renting (it )?out|my tenant|tenants?|"
    r"vacant|empty|nobody (lives|living)|sitting empty|"
    r"my primary|not living|i.?m (not )?there|my main home|"
    r"moved out|don.?t live there"
    r")\b",
    re.IGNORECASE,
)

_CONDITION_PATTERN = re.compile(
    r"\b("
    r"need(s)? (work|repairs?|fixing|updating|attention)|"
    r"good condition|great shape|perfect condition|"
    r"updated|renovated|remodeled|fully updated|"
    r"fixer|as.?is|move.?in ready|gut job|"
    r"torn up|rough shape|dated|run.?down|falling apart|"
    r"pretty good|not bad|needs (some|a lot of|major)"
    r")\b",
    re.IGNORECASE,
)

_MOTIVATION_CONFIRMED_PATTERN = re.compile(
    r"\b("
    r"divorce|divorcing|separated|splitting up|"
    r"foreclosure|behind on (the )?mortgage|notice of default|"
    r"inherited|estate|probate|passed away|my (mom|dad|parent|grandma|grandpa|uncle|aunt) (died|passed)|"
    r"relocat|moving (out|away|out of state)|job transfer|"
    r"need the money|can.?t afford|"
    r"tired (of|landlord|dealing)|bad tenant(s)?|eviction|"
    r"need (out|to get out|to move)|too much to handle|overwhelmed|"
    r"downsiz|kids (moved|are gone)|empty nest|retirement|retiring|"
    r"financial(ly)? (stress|strapped|trouble)|owe more than"
    r")\b",
    re.IGNORECASE,
)

_PRICE_EXPECTATION_PATTERN = re.compile(
    r"\b("
    r"looking (to get|for)|need(ing)? (at least|around|about|\$)|"
    r"want(ing)? (to get|at least)|hoping (to get|for)|"
    r"my number|my price|what i need|"
    r"asking (price)?|was thinking (around|about)|\$\s*\d"
    r")\b",
    re.IGNORECASE,
)

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        logger.warning(
            "extended_prompt_load_failed path={} error={}",
            extended_path,
            str(e),
        )
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


# ---------------------------------------------------------------------------
# ContextTrackerProcessor
# ---------------------------------------------------------------------------

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
                    "ctx_tracker turn={} obj={} mode={} situation={} text={!r}",
                    self._ctx.turn_count,
                    self._ctx.get_current_objective(),
                    self._ctx.get_seller_mode(),
                    self._ctx.situation_label,
                    text[:60],
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

        logger.debug(
            "ctx_tracker injected obj={} forbidden_count={}",
            self._ctx.get_current_objective(),
            len(self._ctx.get_forbidden_moves()),
        )

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

        # --- Acquisition field detection ---

        if not self._ctx.intent_confirmed and _INTENT_CONFIRMED_PATTERN.search(text):
            self._ctx.intent_confirmed = True
            logger.info("intent_confirmed turn={}", self._ctx.turn_count)

        if not self._ctx.occupancy_known and _OCCUPANCY_PATTERN.search(text):
            self._ctx.occupancy_known = True
            logger.info("occupancy_known turn={}", self._ctx.turn_count)

        if not self._ctx.condition_known and _CONDITION_PATTERN.search(text):
            self._ctx.condition_known = True
            logger.info("condition_known turn={}", self._ctx.turn_count)

        if not self._ctx.motivation_known and _MOTIVATION_CONFIRMED_PATTERN.search(text):
            self._ctx.motivation_known = True
            logger.info("motivation_known turn={}", self._ctx.turn_count)

        if not self._ctx.price_expectation_known and _PRICE_EXPECTATION_PATTERN.search(text):
            self._ctx.price_expectation_known = True
            logger.info("price_expectation_known turn={}", self._ctx.turn_count)

        # --- Timeline ---
        timeline = _TIMELINE_PATTERN.search(lower)
        if timeline:
            self._ctx.timeline_mentioned = timeline.group(0)
            if not self._ctx.timeline_known:
                self._ctx.timeline_known = True
                logger.info("timeline_known turn={}", self._ctx.turn_count)

        # --- Price mentions ---
        price = _extract_price_cents(text)
        if price is not None:
            self._ctx.last_price_mentioned = price

        # --- Property issues ---
        for pattern, label in _ISSUE_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.property_issues:
                self._ctx.property_issues.append(label)
                self._ctx.property_issues = self._ctx.property_issues[-8:]

        # --- Motivation signals ---
        for pattern, label in _MOTIVATION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.motivation_signals:
                self._ctx.motivation_signals.append(label)
                self._ctx.motivation_signals = self._ctx.motivation_signals[-8:]

        # --- Objections ---
        for pattern, label in _OBJECTION_PATTERNS:
            if re.search(pattern, lower) and label not in self._ctx.objections_raised:
                self._ctx.objections_raised.append(label)
                self._ctx.objections_raised = self._ctx.objections_raised[-8:]

        # --- Phase (legacy observability) ---
        for target_phase, pattern in _PHASE_TRIGGERS:
            if pattern.search(text):
                self._ctx.advance_phase(target_phase)
                break

        self._update_seller_energy(text)
        self._update_situation_label(text)
        self._update_pacing()
        self._update_silence_hint(text)

    def _update_seller_energy(self, text: str) -> None:
        word_count = len(text.split())

        new_energy: SellerEnergy | None = None

        if word_count > 30:
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

        # Talkative seller past the opening → trigger redirect
        # Renderer will consume this flag and inject a pivot phrase
        if (
            new_energy == "talkative"
            and self._ctx.turn_count > 2
            and self._ctx.intent_confirmed
        ):
            self._ctx.redirect_needed = True
            logger.info(
                "redirect_needed set turn={} objective={}",
                self._ctx.turn_count,
                self._ctx.get_current_objective(),
            )

    def _update_situation_label(self, text: str) -> None:
        if self._ctx.situation_label != "unknown":
            return

        for label, pattern in _SITUATION_PATTERNS:
            if pattern.search(text):
                self._ctx.situation_label = label
                logger.info("situation_label detected label={}", label)
                return

    def _update_pacing(self) -> None:
        """Advance pacing_state as acquisition facts accumulate."""
        ctx = self._ctx
        # Count confirmed fields beyond intent
        fields_known = sum([
            ctx.address_known,
            ctx.motivation_known,
            ctx.occupancy_known,
            ctx.condition_known,
            ctx.timeline_known,
            ctx.price_expectation_known,
        ])

        if ctx.seller_energy == "rushed" or ctx.disposition == "HOT":
            new_state = "tight"
        elif fields_known >= 3 or ctx.intent_confirmed and fields_known >= 2:
            new_state = "tight"
        elif ctx.intent_confirmed or fields_known >= 1:
            new_state = "operational"
        else:
            new_state = "warm"

        # Never regress from tighter to warmer mid-call
        order = ("warm", "operational", "tight")
        if order.index(new_state) > order.index(ctx.pacing_state):
            logger.info(
                "pacing_state advanced from={} to={} fields_known={}",
                ctx.pacing_state,
                new_state,
                fields_known,
            )
            ctx.pacing_state = new_state

    def _update_silence_hint(self, text: str) -> None:
        """Set silence_hint based on seller content — consumed once by renderer."""
        ctx = self._ctx
        if ctx.silence_hint:
            return  # already pending, don't overwrite

        lower = text.lower()

        # Price mention → pause before our response
        if _extract_price_cents(text) is not None or _PRICE_EXPECTATION_PATTERN.search(text):
            ctx.silence_hint = "price"
            return

        # Emotional/hardship disclosure → longer pause
        if _MOTIVATION_CONFIRMED_PATTERN.search(text):
            # Only for the heavy ones
            heavy = re.search(
                r"\b(passed away|died|foreclosure|behind on|divorce|divorcing|can.?t afford)\b",
                lower,
            )
            if heavy:
                ctx.silence_hint = "emotional"
                return

        # Skeptical energy
        if ctx.seller_energy == "skeptical":
            ctx.silence_hint = "skeptical"
