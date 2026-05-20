from __future__ import annotations

import re

from loguru import logger


_TRUST_REPAIR_THRESHOLD = 3.0
_DEAL_HEAT_CLOSE_THRESHOLD = 8.0
_DEAL_HEAT_APPOINTMENT_THRESHOLD = 6.0


_LEGITIMACY_PATTERNS = re.compile(
    r"\b(scam|fake|not real|is this legit|prove it|who are you|"
    r"are you a robot|are you ai|how did you get my number|"
    r"real company|licensed)\b",
    re.IGNORECASE,
)

_HOSTILE_PATTERNS = re.compile(
    r"\b(stop calling|remove me|leave me alone|lawsuit|"
    r"not interested|never selling|do not call)\b",
    re.IGNORECASE,
)

_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_BLOCKING_LEVELS = frozenset(["BLOCKING"])
_CRITICAL_FATIGUE = frozenset(["CRITICAL"])


class ObjectiveEngine:
    def decide(self, call_ctx) -> str:
        trust = getattr(call_ctx, "trust_score", 5.0)
        emotional_state = getattr(call_ctx, "emotional_state", "NEUTRAL")
        resistance_level = getattr(call_ctx, "resistance_level", "NONE")
        resistance_softening = getattr(call_ctx, "resistance_softening", False)
        deal_heat = getattr(call_ctx, "deal_heat", 0.0)
        fatigue_level = getattr(call_ctx, "fatigue_level", "FRESH")
        microstate = getattr(call_ctx, "microstate", "NEUTRAL")
        turn_count = getattr(call_ctx, "turn_count", 0)
        address_known = getattr(call_ctx, "address_known", False)
        intent_locked = getattr(call_ctx, "intent_locked", False)
        motivation_signals = getattr(call_ctx, "motivation_signals", [])
        property_issues = getattr(call_ctx, "property_issues", [])
        timeline_mentioned = getattr(call_ctx, "timeline_mentioned", None)
        last_price_mentioned = getattr(call_ctx, "last_price_mentioned", None)
        has_agent = getattr(call_ctx, "has_agent", False)
        mortgage_status = getattr(call_ctx, "mortgage_status", "unknown")
        objections_raised = getattr(call_ctx, "objections_raised", [])

        if trust < _TRUST_REPAIR_THRESHOLD:
            logger.debug("objective=TRUST_REPAIR trust={:.1f}", trust)
            return "TRUST_REPAIR"

        if emotional_state in _DISTRESSED_STATES and turn_count <= 3:
            logger.debug("objective=EMOTIONAL_HOLD state={}", emotional_state)
            return "EMOTIONAL_HOLD"

        if microstate == "COMMITTING":
            logger.debug("objective=BOOK_APPOINTMENT microstate=COMMITTING")
            return "BOOK_APPOINTMENT"

        if deal_heat >= _DEAL_HEAT_CLOSE_THRESHOLD:
            logger.debug("objective=BOOK_APPOINTMENT heat={:.1f}", deal_heat)
            return "BOOK_APPOINTMENT"

        if resistance_level in _BLOCKING_LEVELS and not resistance_softening:
            logger.debug("objective=HANDLE_OBJECTION resistance={}", resistance_level)
            return "HANDLE_OBJECTION"

        if objections_raised and resistance_softening:
            logger.debug("objective=LEAN_IN softening=True")
            return "LEAN_IN"

        if fatigue_level in _CRITICAL_FATIGUE:
            logger.debug("objective=NURTURE_EXIT fatigue=CRITICAL")
            return "NURTURE_EXIT"

        if not address_known:
            logger.debug("objective=GET_ADDRESS")
            return "GET_ADDRESS"

        if not intent_locked or not motivation_signals:
            logger.debug("objective=GET_MOTIVATION")
            return "GET_MOTIVATION"

        if emotional_state in _DISTRESSED_STATES:
            logger.debug("objective=EMOTIONAL_HOLD state={}", emotional_state)
            return "EMOTIONAL_HOLD"

        if has_agent:
            logger.debug("objective=HANDLE_OBJECTION has_agent=True")
            return "HANDLE_OBJECTION"

        if not timeline_mentioned:
            logger.debug("objective=GET_TIMELINE")
            return "GET_TIMELINE"

        if not property_issues:
            logger.debug("objective=GET_CONDITION")
            return "GET_CONDITION"

        if mortgage_status == "unknown" and turn_count >= 5:
            logger.debug("objective=GET_MORTGAGE")
            return "GET_MORTGAGE"

        if last_price_mentioned and not timeline_mentioned:
            logger.debug("objective=GET_PRICE_ANCHOR")
            return "GET_PRICE_ANCHOR"

        if deal_heat >= _DEAL_HEAT_APPOINTMENT_THRESHOLD:
            logger.debug("objective=BOOK_APPOINTMENT heat={:.1f}", deal_heat)
            return "BOOK_APPOINTMENT"

        if timeline_mentioned and motivation_signals and property_issues:
            logger.debug("objective=BOOK_APPOINTMENT all_signals_known")
            return "BOOK_APPOINTMENT"

        logger.debug("objective=GET_MOTIVATION default")
        return "GET_MOTIVATION"