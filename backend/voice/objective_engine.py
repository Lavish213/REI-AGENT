from __future__ import annotations
import re
from loguru import logger

_TRUST_REPAIR_THRESHOLD = 3.0
_BLOCKING_LEVELS = frozenset(["BLOCKING"])
_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_CRITICAL_FATIGUE = frozenset(["CRITICAL"])

_LEGITIMACY_PATTERNS = re.compile(
    r"\b(scam|fake|not real|is this legit|prove it|who are you|"
    r"are you a robot|are you ai|how did you get my number|"
    r"real company|licensed)\b",
    re.IGNORECASE,
)


class ObjectiveEngine:
    def decide(self, call_ctx) -> str:
        return self._decide_impl(call_ctx)

    def _decide_impl(self, call_ctx) -> str:
        _PHASE_TO_STAGE = {
            "VERIFY":          "STAGE_1_QUALIFY",
            "LIGHT_DISCOVERY": "STAGE_2_DISCOVER",
            "QUALIFY":         "STAGE_3_PRECLOSE",
            "NEXT_STEP":       "STAGE_4_CLOSE",
            "WRAP":            "STAGE_5_WRAP",
        }
        _STAGE_ORDER = [
            "STAGE_1_QUALIFY",
            "STAGE_2_DISCOVER",
            "STAGE_3_PRECLOSE",
            "STAGE_4_CLOSE",
            "STAGE_5_WRAP",
        ]
        _SAFETY = {"TRUST_REPAIR", "EMOTIONAL_HOLD", "HANDLE_OBJECTION", "STAGE_5_WRAP"}
        bob_phase = getattr(call_ctx, "bob_phase", None)
        bob_floor = _PHASE_TO_STAGE.get(bob_phase) if bob_phase else None

        def _apply_floor(stage: str) -> str:
            if not bob_floor or stage in _SAFETY:
                return stage
            try:
                if _STAGE_ORDER.index(stage) < _STAGE_ORDER.index(bob_floor):
                    return bob_floor
            except ValueError:
                pass
            return stage

        trust = getattr(call_ctx, "trust_score", 5.0)
        emotional_state = getattr(call_ctx, "emotional_state", "NEUTRAL")
        resistance_level = getattr(call_ctx, "resistance_level", "NONE")
        resistance_softening = getattr(call_ctx, "resistance_softening", False)
        fatigue_level = getattr(call_ctx, "fatigue_level", "FRESH")
        turn_count = getattr(call_ctx, "turn_count", 0)
        owner_confirmed = getattr(call_ctx, "owner_confirmed", False)
        address_known = getattr(call_ctx, "address_known", False)
        intent_locked = getattr(call_ctx, "intent_locked", False)
        motivation_signals = getattr(call_ctx, "motivation_signals", [])
        property_issues = getattr(call_ctx, "property_issues", [])
        timeline_mentioned = getattr(call_ctx, "timeline_mentioned", None)
        mortgage_status = getattr(call_ctx, "mortgage_status", "unknown")
        pre_close_done = getattr(call_ctx, "pre_close_done", False)
        appointment_set = getattr(call_ctx, "appointment_set", False)
        disposition = getattr(call_ctx, "disposition", None)
        deal_heat = getattr(call_ctx, "deal_heat", 0.0)
        microstate = getattr(call_ctx, "microstate", "NEUTRAL")

        bob_phase = getattr(call_ctx, "bob_phase", "VERIFY")
        _PHASE_ORDER = ["VERIFY", "LIGHT_DISCOVERY", "QUALIFY", "NEXT_STEP", "WRAP"]
        _STAGE_ORDER = [
            "STAGE_1_QUALIFY", "STAGE_2_DISCOVER",
            "STAGE_3_PRECLOSE", "STAGE_4_CLOSE", "STAGE_5_WRAP"
        ]
        _BOB_TO_STAGE = {
            "VERIFY": "STAGE_1_QUALIFY",
            "LIGHT_DISCOVERY": "STAGE_2_DISCOVER",
            "QUALIFY": "STAGE_2_DISCOVER",
            "NEXT_STEP": "STAGE_3_PRECLOSE",
            "WRAP": "STAGE_5_WRAP",
        }
        bob_floor_stage = _BOB_TO_STAGE.get(bob_phase, "STAGE_1_QUALIFY")

        if disposition in ("DEAD", "HOT", "WARM", "COLD"):
            logger.debug("objective=STAGE_5_WRAP disposition={}", disposition)
            return "STAGE_5_WRAP"

        if fatigue_level in _CRITICAL_FATIGUE and turn_count >= 6:
            logger.debug("objective=STAGE_5_WRAP fatigue_critical")
            return "STAGE_5_WRAP"

        if trust < _TRUST_REPAIR_THRESHOLD:
            logger.debug("objective=TRUST_REPAIR trust={:.1f}", trust)
            return "TRUST_REPAIR"

        if emotional_state in _DISTRESSED_STATES:
            logger.debug("objective=EMOTIONAL_HOLD state={}", emotional_state)
            return "EMOTIONAL_HOLD"

        if resistance_level in _BLOCKING_LEVELS and not resistance_softening:
            logger.debug("objective=HANDLE_OBJECTION resistance=BLOCKING")
            return "HANDLE_OBJECTION"

        qualify_gate = (
            (owner_confirmed or address_known) and (intent_locked or bool(motivation_signals))
        ) or turn_count >= 4
        if not qualify_gate:
            logger.debug("objective=STAGE_1_QUALIFY owner={} intent={} turn={}", owner_confirmed, intent_locked, turn_count)
            return _apply_floor("STAGE_1_QUALIFY")

        mortgage_ok = mortgage_status != "unknown" or turn_count < 6
        discover_gate = (
            bool(motivation_signals)
            and (bool(property_issues) or turn_count >= 8)
            and (bool(timeline_mentioned) or turn_count >= 6)
            and mortgage_ok
        )
        if not discover_gate:
            logger.debug("objective=STAGE_2_DISCOVER motivation={} condition={} timeline={} mortgage={}",
                bool(motivation_signals), bool(property_issues), bool(timeline_mentioned), mortgage_status)
            return _apply_floor("STAGE_2_DISCOVER")

        if not pre_close_done:
            logger.debug("objective=STAGE_3_PRECLOSE")
            return _apply_floor("STAGE_3_PRECLOSE")

        if not appointment_set:
            logger.debug("objective=STAGE_4_CLOSE heat={:.1f} microstate={}", deal_heat, microstate)
            return _apply_floor("STAGE_4_CLOSE")

        logger.debug("objective=STAGE_5_WRAP")
        return "STAGE_5_WRAP"
