from __future__ import annotations

import re
import asyncio
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger
from pipecat.frames.frames import Frame, LLMContextFrame, TTSSpeakFrame, EndFrame
from pipecat.frames.frames import TranscriptionFrame, UserStartedSpeakingFrame
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
    "sell it",
    "selling it",
    "fix and sell",
    "fix to sell",
    "trying to sell it",
    "want to get out",
    "ready to sell",
]

_ADDRESS_PATTERN = re.compile(
    r"(?:"
    r"\b\d{3,5}\s+[A-Za-z][\w\s]{2,30}"
    r"(?:st|ave|blvd|dr|ln|rd|ct|way|pl|cir|ter|street|avenue|boulevard|drive|lane|road|court|place|circle|terrace)\b"
    r"|"
    r"\b(?:on|at|off)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
    r"(?:st|ave|blvd|dr|ln|rd|ct|way|pl|cir|ter|street|avenue|boulevard|drive|lane|road|court|place|circle|terrace)\b"
    r"|"
    r"\b(?:west|east|north|south)\s+\w+\s+"
    r"(?:st|ave|blvd|dr|ln|rd|ct|way|pl|cir|ter|street|avenue|boulevard|drive|lane|road|court|place|circle|terrace)\b"
    r")",
    re.IGNORECASE,
)

_TIMELINE_PATTERN = re.compile(
    r"\b("
    r"asap|immediately|today|tomorrow|next (?:week|month|year)|"
    r"(?:in |within )?\d+ (?:days?|weeks?|months?)|few months|this (?:week|month)|"
    r"no rush|not in a hurry|when (?:i|we)(?: am| are|\x27m|\x27re)? ready"
    r")\b",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(
    r"(?<![\w.-])(?:\$\s*)?(\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.(\d{1,2}))?\s*(k|thousand|grand)?(?![\w.])",
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
    ("rushed", re.compile(r"\b(asap|immediately|today|tomorrow|next week|next month|30 days|60 days|90 days|few months|this week|this month|end of year|by summer|couple months|no rush|not in a hurry|whenever|flexible|soon|right away|as soon as|within)\b", re.IGNORECASE)),
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
    transcript_events: list[dict] = field(default_factory=list)
    seller_name: str | None = None
    seller_energy: SellerEnergy = "calm"
    energy_history: list[str] = field(default_factory=list)
    situation_label: SituationLabel = "unknown"
    last_question_topic: str = ""
    condition_known: bool = False
    response_goal: str = ""
    response_guidance: str = ""
    awaiting_owner_confirmation: bool = False
    property_issues: list[str] = field(default_factory=list)
    motivation_signals: list[str] = field(default_factory=list)
    objections_raised: list[str] = field(default_factory=list)
    last_price_mentioned: int | None = None
    timeline_mentioned: str | None = None
    disposition: str | None = None
    turn_count: int = 0
    owner_confirmed: bool = False
    pre_close_done: bool = False
    _walkthrough_asked: bool = False
    property_address: str = ""
    appointment_set: bool = False
    callback_set: bool = False
    _dnc_flagged: bool = False
    address_known: bool = False
    intent_locked: bool = False
    extended_loaded: bool = False

    has_agent: bool = False

    mortgage_status: str = "unknown"
    free_and_clear: bool = False
    price_resistance: bool = False

    objective: str = "STAGE_1_QUALIFY"
    runtime_instruction: str | None = None
    is_outbound: bool = False
    seller_name_used_count: int = 0

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
    stop_requested: bool = False
    seller_phone: str = ""
    lead_id: str = ""
    _opener_text: str = ""
    _opener_fired: bool = False
    _task_ref: object = None
    _call_sid: str = ""
    orchestrator_length_cap: int | None = None
    memory_context_str: str = ""
    intel_packet: dict = None
    packet_version: int = 0
    packet_state: str = "missing"
    extracted_entities: dict = None
    action_permissions: dict = None
    conflict_active: bool = False
    kill_switch_active: bool = False
    approval_pending: str | None = None
    fallback_mode: bool = False
    last_sophia_words: int = 0
    tts_speed: float = 0.85
    tts_volume: float = 0.85
    call_brief: dict = field(default_factory=dict)
    bob_phase: str | None = None
    bob_missing_box: str | None = None
    bob_mood_hint: str | None = None
    bob_avoid: list = field(default_factory=list)
    bob_escalation_rules: list = field(default_factory=list)
    bob_opener_hint: str | None = None

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
        _OBJ_MAP = {
            "STAGE_1_QUALIFY": "Confirm the intended person and ask whether this is a good time. Respect a no.",
            "STAGE_2_DISCOVER": "React first. Ask one relevant missing question about motivation, timeline, or condition. Answer the caller's questions first.",
            "STAGE_3_PRECLOSE": "Ask whether a no-obligation walkthrough would be useful. Wait for their answer.",
            "STAGE_4_CLOSE": "Agree an exact future date, local time, timezone, and address. Confirm with the seller, then reserve through the tool. Never promise unverified availability.",
            "STAGE_5_WRAP": "Confirm only the next step that was actually saved, resolve open questions, and end warmly. Do not request referrals after an opt-out or rejection.",
            "HANDLE_OBJECTION": "Answer directly, respect the caller's preference, and do not pressure them.",
            "TRUST_REPAIR": "Answer directly with verified facts. No sales push.",
            "EMOTIONAL_HOLD": "Acknowledge briefly and empathetically. Let the caller finish. Offer another time or a human when helpful.",
            "BOOK_APPOINTMENT": "Ask for an exact date and time, confirm timezone and address, then use the booking tool.",
            "GET_MOTIVATION": "Ask a relevant question only if the motivation is unknown.",
            "GET_TIMELINE": "Ask what timing works for them only if unknown.",
            "GET_MORTGAGE": "Ask about a loan only if relevant; do not assume there is one.",
            "GET_ADDRESS": "Confirm the actual property address if unknown.",
        }
        _MODE_MAP = {
            "FAST": "keep it brief and get to the point",
            "DISTRESSED": "slow down and follow their story",
            "HOT": "move toward setting the appointment",
            "SKEPTICAL": "shorter responses, grounded language, answer their questions",
            "INHERITED": "acknowledge the loss naturally before anything else",
            "EMOTIONAL": "match their energy and follow the emotion first",
            "LANDLORD": "lead with simplicity and no hassle",
            "STANDARD": "normal curious discovery flow",
        }

        obj = self.objective or "GET_MOTIVATION"
        mode = self.get_seller_mode()
        addr = "yes" if self.address_known else "no"
        intent = "yes" if self.intent_locked else "no"
        appt = "yes" if getattr(self, "appointment_set", False) else "no"

        goal = _OBJ_MAP.get(obj, "understand their situation")
        tone = _MODE_MAP.get(mode, "stay curious and warm")

        comm_style = getattr(self, "_ctx", self).comm_style if hasattr(self, "_ctx") else getattr(self, "comm_style", "STANDARD")
        sophistication = getattr(self, "_ctx", self).seller_sophistication if hasattr(self, "_ctx") else "AVERAGE"
        comm_note = f"\nSeller style: {comm_style.lower()}" if comm_style != "STANDARD" else ""
        savvy_note = f"\nSeller savvy: {sophistication.lower()}" if sophistication != "AVERAGE" else ""
        arv = None
        mao = None
        distress = None
        try:
            packet = getattr(self._ctx, "intel_packet", None) or {}
            prop_profile = packet.get("property_profile") or {}
            arv_data = prop_profile.get("arv") or {}
            mao_data = prop_profile.get("mao") or {}
            dist_data = prop_profile.get("distress_type") or {}
            arv = arv_data.get("value")
            mao = mao_data.get("value")
            distress = dist_data.get("value")
        except Exception:
            pass
        arv_note = f"\nARV: ${arv:,.0f}" if arv else ""
        mao_note = f" | MAO: ${mao:,.0f}" if mao else ""
        distress_note = f" | Situation: {distress}" if distress else ""
        tag = (
            f"Current goal: {goal}\n"
            f"Seller tone: {tone}\n"
            f"Address collected: {addr}\n"
            f"Selling intent confirmed: {intent}\n"
            f"Appointment set: {appt}"
            + comm_note + savvy_note + arv_note + mao_note + distress_note
        )

        if self.property_address:
            tag += f"\nProperty address confirmed in this call: {self.property_address}"

        if self.objections_raised:
            tag += f"\nLast objection raised: {self.objections_raised[-1]}"

        if self.runtime_instruction:
            tag += f"\nContext: {self.runtime_instruction}"

        sections = []

        intel_packet = self.intel_packet or {}
        if intel_packet and self.packet_state not in ("missing", "fallback"):
            from backend.contracts.intel_packet import build_prompt_intel_slice
            intel_slice = build_prompt_intel_slice(intel_packet)
            if intel_slice:
                sections.append(intel_slice)
        if self.conflict_active:
            sections.append("CONFLICT: Ask operator before any offer or strategy discussion.")
        if self.kill_switch_active:
            sections.append("KILL SWITCH: Route to safe fallback only. No strategy. No offers.")

        if self.bob_avoid:
            tag += f"\nAvoid: {', '.join(self.bob_avoid)}"
        if self.bob_missing_box:
            tag += f"\nFocus on: {self.bob_missing_box}"
        sections.append(tag + "\nSTYLE: short, reactive, human. 1-2 sentences. one question. react before asking.")

        if self.response_guidance:
            sections.append(self.response_guidance)
        return "\n\n".join(sections)


def _extract_price_cents(text: str) -> int | None:
    from decimal import Decimal
    candidates = []
    for match in _PRICE_PATTERN.finditer(text):
        before = text[max(0, match.start() - 45):match.start()].lower()
        after = text[match.end():match.end() + 25].lower()
        before = re.split(r"[,;!?]", before)[-1]
        explicit = bool(re.search(r"\b(asking|offer|price|want|worth|looking for|would take|precio|pido)\b", before))
        debt = bool(re.search(r"\b(mortgage|owe|loan|balance|debt|hipoteca|debo)\b", before + " " + after))
        if debt and not explicit:
            continue
        suffix = (match.group(3) or "").lower()
        if "$" not in match.group(0) and not suffix and not explicit:
            continue
        if re.search(r"\$\s*-\s*$", before):
            continue
        value = Decimal(match.group(1).replace(",", "") + ("." + match.group(2) if match.group(2) else ""))
        if suffix:
            value *= 1000
        if value <= 0 or (value < 1000 and "$" not in match.group(0) and not suffix):
            continue
        candidates.append((explicit, int(value * 100)))
    if not candidates:
        return None
    return max(reversed(candidates), key=lambda item: item[0])[1]


class ContextTrackerProcessor(FrameProcessor):
    def __init__(self, call_ctx: CallContext, llm_context=None):
        super().__init__()
        self._ctx = call_ctx
        self._llm_context = llm_context
        self._last_context_prefix: str | None = None
        self._objective_engine = None

    @property
    def _task_ref(self):
        return getattr(self._ctx, "_task_ref", None)

    @property
    def _task_ref(self):
        return getattr(self._ctx, "_task_ref", None)

    def set_objective_engine(self, engine) -> None:
        self._objective_engine = engine

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame) and frame.text:
            text = frame.text.strip()

            if text:
                self._ctx.turn_count += 1
                self._analyze(text)
                _tc = self._ctx.turn_count
                _is_ob = getattr(self._ctx, "is_outbound", False)
                if _is_ob and self._ctx.awaiting_owner_confirmation and not self._ctx.owner_confirmed:
                    import re as _re2
                    if _re2.search(r"\b(yes|yeah|yep|yup|correct|right|speaking|that's me|this is)\b", text, _re2.IGNORECASE) and not _re2.search(r"\b(never|not|no|won't|wont)\b", text, _re2.IGNORECASE):
                        self._ctx.owner_confirmed = True
                        self._ctx.awaiting_owner_confirmation = False
                        logger.info("owner_confirmed via affirmative turn={}", _tc)
                import re as _re
                _DNC = _re.compile(r"\b(stop calling|stop contacting(?: me)?|take me off|do not call|don.t call(?: me)?(?: again)?|remove me|lose my number|never call again|leave me alone|no me llames|no me vuelvas a llamar|qu[ií]tame de (?:tu|su) lista|deja de llamar)\b", _re.IGNORECASE)
                if _DNC.search(text) and not getattr(self._ctx, "_dnc_flagged", False):
                    self._ctx._dnc_flagged = True
                    self._ctx.runtime_instruction = None
                    logger.warning("dnc_signal_detected")
                    from backend.voice.tools import execute_tool
                    await asyncio.to_thread(execute_tool, "honor_stop_request", {"verbatim": text}, self._ctx)
                    self._ctx.call_should_end = True
                    if self._ctx._task_ref:
                        await self._ctx._task_ref.queue_frames([TTSSpeakFrame("Understood. We'll stop contacting you. Goodbye."), EndFrame()])
                    return

                if self._objective_engine is not None:
                    self._ctx.objective = self._objective_engine.decide(self._ctx)

                current_turn = self._ctx.turn_count
                if getattr(self, "_last_injected_turn", -1) != current_turn:
                    self._inject_context_prefix()
                    self._last_injected_turn = current_turn
                    try:
                        from backend.karpathys import emitter as _ke
                        import asyncio as _aio
                        _sid = getattr(self._ctx, "_call_sid", "") or ""
                        _trust = getattr(self._ctx, "trust_score", None)
                        _heat = getattr(self._ctx, "deal_heat", None)
                        _turn = getattr(self._ctx, "turn_count", 0)
                        if _sid:
                            _aio.create_task(_ke.emit_turn_completed(
                                call_sid=_sid,
                                speaker="user",
                                text=text,
                                trust_score=_trust,
                                deal_heat=_heat,
                                turn_index=_turn,
                            ))
                    except Exception:
                        pass
                    energy = getattr(self._ctx, "seller_energy", "calm") or "calm"
                    tts_svc = getattr(self, "_tts_service_ref", None)
                    if tts_svc and hasattr(tts_svc, "_settings") and energy != getattr(self, "_last_energy", "calm"):
                        self._last_energy = energy
                        logger.debug("context_tracker emotion_hint energy={}", energy)

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
            compressed = await compress_context(
                self._llm_context.messages,
                self._ctx.objective,
            )
            self._llm_context.set_messages(compressed)
            logger.info("context compressed messages={}", len(compressed))
        except Exception as error:
            logger.warning("context compression failed error={}", str(error))

    def _trim_history(self) -> None:
        messages = getattr(self._llm_context, "messages", None)
        if not messages:
            return
        system = [m for m in messages if m.get("role") == "system"]
        turns = [m for m in messages if m.get("role") != "system"]
        if len(turns) <= 8:
            return
        kept = turns[-8:]
        import re as _re_t
        for m in kept:
            if m.get("role") != "user":
                continue
            c = m.get("content", "")
            if isinstance(c, str):
                c = _re_t.sub(r"<ctx>[\s\S]*?</ctx>\s*", "", c).strip()
                c = _re_t.sub(r"<seller>([\s\S]*?)</seller>", r"\1", c).strip()
                m["content"] = c
        self._llm_context.set_messages(system + kept)
        logger.debug("history_trimmed kept={}", len(kept))

    def _inject_context_prefix(self) -> None:
        if not self._llm_context:
            return
        messages = self._llm_context.messages
        prefix = self._ctx.build_context_prefix()
        memory = self._ctx.memory_context_str
        content = "[CURRENT CALL STATE]\n" + (memory + "\n" if memory else "") + prefix
        state = next((m for m in messages if m.get("role") == "system" and isinstance(m.get("content"), str) and m["content"].startswith("[CURRENT CALL STATE]")), None)
        if state is None:
            messages.insert(1, {"role": "system", "content": content})
        else:
            state["content"] = content
        self._last_context_prefix = prefix

    def _analyze(self, text: str) -> None:
        lower = text.lower().replace("’", "'")
        conditional_sale = re.search(r"\bnot selling\s+(?:until|before|unless|yet)\b", lower)
        if not conditional_sale and re.search(r"\b(not selling|don't want to sell|no longer (?:selling|want to sell)|not (?:going to|trying to) sell)\b", lower):
            self._ctx.intent_locked = False
            self._ctx.pre_close_done = False
        if re.search(r"\b(i own|i'm the owner|i am the owner|it's my (?:house|property)|my house)\b", lower) and not re.search(r"\b(not|don't)\b.{0,15}\bown", lower):
            self._ctx.owner_confirmed = True
        if re.search(r"\b(good (?:shape|condition)|no repairs|needs? (?:work|repairs)|new roof|move.in ready|as.is|fixer|roof|plumbing|foundation|renovated)\b", lower):
            self._ctx.condition_known = True
        if self._ctx._walkthrough_asked and re.search(r"\b(yes|yeah|sure|sounds good|works for me|let.s do it)\b", lower) and not re.search(r"\b(no|not|never|maybe|but|if|depends|possibly)\b", lower):
            self._ctx.pre_close_done = True
            self._ctx._walkthrough_asked = False

        price = _extract_price_cents(text)
        if price is None and self._ctx.last_question_topic == "price" and re.fullmatch(r"\s*\d[\d,.]*\s*", text):
            price = _extract_price_cents("Asking $" + text.strip())
        if price is not None:
            self._ctx.last_price_mentioned = price

        timeline_match = _TIMELINE_PATTERN.search(lower)
        if timeline_match:
            self._ctx.timeline_mentioned = timeline_match.group(0)

        for pattern, label in _ISSUE_PATTERNS:
            if re.search(r"\b(?:no|not|new|fixed|replaced|repaired)\b(?:\s+(?:problems?|issues?|with|the|a|any|my|our|need|for)){0,3}\s+" + pattern, lower) or re.search(pattern + r".{0,15}\b(?:fine|fixed|new|good|replaced)\b", lower):
                if label in self._ctx.property_issues:
                    self._ctx.property_issues.remove(label)
            elif re.search(pattern, lower):
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

        if not self._ctx.intent_locked and any(phrase in lower for phrase in _INTENT_PHRASES) and not re.search(r"\b(not|never|don.t|won.t|isn.t|aren.t)\b.{0,25}\b(sell|selling|move|moving)\b", lower):
            self._ctx.intent_locked = True
            logger.info("seller intent locked")

        address = _ADDRESS_PATTERN.search(text)
        if address:
            self._ctx.address_known = True
            self._ctx.property_address = address.group(0)
            logger.info("property address detected")

        if re.search(r"\b(no agent|not (?:using|working with) (?:an? )?agent|don.t have (?:an? )?agent)\b", lower):
            self._ctx.has_agent = False
        elif not self._ctx.has_agent and _AGENT_PATTERN.search(text):
            self._ctx.has_agent = True
            logger.info("agent detected")

        clear_match = _FREE_CLEAR_PATTERN.search(text)
        negated_clear = clear_match and re.search(r"\b(not|never|don.t|isn.t|aren.t)\b.{0,25}$", text[max(0, clear_match.start() - 35):clear_match.start()], re.I)
        if clear_match and not negated_clear:
            self._ctx.free_and_clear = True
            self._ctx.mortgage_status = "clear"
        elif negated_clear or _MORTGAGE_HIGH_PATTERN.search(text):
            self._ctx.free_and_clear = False
            self._ctx.mortgage_status = "has_mortgage"

        self._update_seller_energy(text)
        self._update_situation_label(text)

    def _update_seller_energy(self, text: str) -> None:
        if re.search(r"\b(no rush|not in a hurry|no hurry)\b", text, re.I):
            self._ctx.seller_energy = "calm"
            return
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

class ContextStateProcessor(FrameProcessor):
    def __init__(self, tracker):
        super().__init__()
        self._tracker = tracker

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            self._tracker._inject_context_prefix()
            self._tracker._ctx.runtime_instruction = None
        await self.push_frame(frame, direction)
