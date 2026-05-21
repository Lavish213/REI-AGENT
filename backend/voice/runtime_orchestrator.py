from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass
class OrchestratorDecision:
    objective_override: str | None = None
    response_length_cap: int | None = None
    inject_instruction: str | None = None
    end_call: bool = False
    end_reason: str | None = None
    decision_reason: str = ""


_TRUST_CRITICAL = 2.5
_TRUST_REPAIR = 3.5
_DEAL_HEAT_CLOSE = 8.0
_DEAL_HEAT_APPT = 6.0
_MOMENTUM_STALL = 3.0
_FATIGUE_EXIT = frozenset(["CRITICAL"])
_DISTRESSED_STATES = frozenset(["DISTRESSED", "GRIEVING", "OVERWHELMED"])
_HIGH_RESISTANCE = frozenset(["HIGH", "BLOCKING"])


class RuntimeOrchestrator:
    def decide(self, call_ctx) -> OrchestratorDecision:
        trust = getattr(call_ctx, "trust_score", 5.0)
        emotional_state = getattr(call_ctx, "emotional_state", "NEUTRAL")
        resistance_level = getattr(call_ctx, "resistance_level", "NONE")
        resistance_softening = getattr(call_ctx, "resistance_softening", False)
        deal_heat = getattr(call_ctx, "deal_heat", 0.0)
        fatigue_level = getattr(call_ctx, "fatigue_level", "FRESH")
        microstate = getattr(call_ctx, "microstate", "NEUTRAL")
        momentum_score = getattr(call_ctx, "momentum_score", 5.0)
        turn_count = getattr(call_ctx, "turn_count", 0)
        call_should_end = getattr(call_ctx, "call_should_end", False)

        if call_should_end:
            logger.info("orchestrator end_call call_should_end=True")
            return OrchestratorDecision(
                end_call=True,
                end_reason="silence_timeout",
                decision_reason="3 consecutive silences",
            )

        if trust < _TRUST_CRITICAL and resistance_level in _HIGH_RESISTANCE:
            logger.info("orchestrator end_call trust_critical resistance_high")
            return OrchestratorDecision(
                end_call=True,
                end_reason="trust_collapsed",
                decision_reason="trust critical + blocking resistance",
            )

        if microstate == "COMMITTING" and deal_heat >= _DEAL_HEAT_CLOSE:
            logger.info("orchestrator BOOK_APPOINTMENT committing + heat={:.1f}", deal_heat)
            return OrchestratorDecision(
                objective_override="BOOK_APPOINTMENT",
                response_length_cap=2,
                inject_instruction=(
                    "Seller is ready to move forward. "
                    "Go directly to appointment. "
                    "Two time options only. "
                    "No more discovery questions."
                ),
                decision_reason="seller committing + deal heat high",
            )

        if trust < _TRUST_REPAIR:
            logger.info("orchestrator TRUST_REPAIR trust={:.1f}", trust)
            return OrchestratorDecision(
                objective_override="TRUST_REPAIR",
                response_length_cap=2,
                inject_instruction=(
                    "Seller is questioning legitimacy. "
                    "Answer directly and simply. "
                    "No sales language. "
                    "Pure facts only. "
                    "Do not push forward."
                ),
                decision_reason="trust below repair threshold",
            )

        if microstate == "VENTING" and emotional_state in _DISTRESSED_STATES:
            logger.info("orchestrator EMOTIONAL_HOLD venting + {}", emotional_state)
            return OrchestratorDecision(
                objective_override="EMOTIONAL_HOLD",
                response_length_cap=1,
                inject_instruction=(
                    "Seller is venting. "
                    "Acknowledge only. "
                    "One short empathetic response. "
                    "No questions. "
                    "No sales pressure. "
                    "Let them finish."
                ),
                decision_reason="seller venting in distressed state",
            )

        if fatigue_level in _FATIGUE_EXIT:
            logger.info("orchestrator NURTURE_EXIT fatigue=CRITICAL")
            return OrchestratorDecision(
                objective_override="NURTURE_EXIT",
                response_length_cap=2,
                inject_instruction=(
                    "Seller is fatigued. "
                    "Wrap up warmly. "
                    "Confirm follow-up. "
                    "End call gracefully."
                ),
                decision_reason="fatigue critical",
            )

        if resistance_softening and resistance_level in _HIGH_RESISTANCE:
            logger.info("orchestrator LEAN_IN softening detected")
            return OrchestratorDecision(
                response_length_cap=2,
                inject_instruction=(
                    "Resistance is softening. "
                    "Lean in gently. "
                    "Do not back off. "
                    "One soft qualifying question."
                ),
                decision_reason="resistance softening",
            )

        if deal_heat >= _DEAL_HEAT_APPT and momentum_score >= 6.0:
            logger.info(
                "orchestrator BOOK_APPOINTMENT heat={:.1f} momentum={:.1f}",
                deal_heat,
                momentum_score,
            )
            return OrchestratorDecision(
                objective_override="BOOK_APPOINTMENT",
                response_length_cap=3,
                inject_instruction=(
                    "Lead is hot. "
                    "Move toward appointment naturally. "
                    "Don't force it but create the opening."
                ),
                decision_reason="deal heat + momentum sufficient",
            )

        if momentum_score < _MOMENTUM_STALL and turn_count > 5:
            logger.info("orchestrator compress momentum_stall={:.1f}", momentum_score)
            return OrchestratorDecision(
                response_length_cap=2,
                inject_instruction=(
                    "Conversation momentum is low. "
                    "Tighten responses. "
                    "Ask one direct question. "
                    "Do not over-explain."
                ),
                decision_reason="momentum stalling",
            )

        return OrchestratorDecision(
            decision_reason="no override standard flow",
        )