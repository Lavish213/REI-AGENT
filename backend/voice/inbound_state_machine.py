from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from loguru import logger


InboundMicroState = Literal[
    "greeting",
    "permission",
    "motivation_probe",
    "condition_probe",
    "timeline_probe",
    "price_probe",
    "appointment_softener",
    "appointment_lock",
    "follow_up_soft_hold",
    "wrap_up",
    "dead_call",
]


class InboundState(str, Enum):
    OPENING = "opening"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    NEGOTIATION = "negotiation"
    APPOINTMENT = "appointment"
    FOLLOW_UP = "follow_up"
    RECOVERY = "recovery"
    CLOSED = "closed"


_VALID_TRANSITIONS: dict[
    InboundState,
    list[InboundState],
] = {
    InboundState.OPENING: [
        InboundState.DISCOVERY,
        InboundState.RECOVERY,
        InboundState.CLOSED,
    ],
    InboundState.DISCOVERY: [
        InboundState.QUALIFICATION,
        InboundState.NEGOTIATION,
        InboundState.FOLLOW_UP,
        InboundState.RECOVERY,
        InboundState.CLOSED,
    ],
    InboundState.QUALIFICATION: [
        InboundState.NEGOTIATION,
        InboundState.APPOINTMENT,
        InboundState.FOLLOW_UP,
        InboundState.RECOVERY,
        InboundState.CLOSED,
    ],
    InboundState.NEGOTIATION: [
        InboundState.APPOINTMENT,
        InboundState.FOLLOW_UP,
        InboundState.RECOVERY,
        InboundState.CLOSED,
    ],
    InboundState.APPOINTMENT: [
        InboundState.CLOSED,
        InboundState.FOLLOW_UP,
        InboundState.RECOVERY,
    ],
    InboundState.FOLLOW_UP: [
        InboundState.CLOSED,
        InboundState.RECOVERY,
    ],
    InboundState.RECOVERY: [
        InboundState.DISCOVERY,
        InboundState.QUALIFICATION,
        InboundState.NEGOTIATION,
        InboundState.APPOINTMENT,
        InboundState.FOLLOW_UP,
        InboundState.CLOSED,
    ],
    InboundState.CLOSED: [],
}


_STATE_OBJECTIVES: dict[
    InboundState,
    str,
] = {
    InboundState.OPENING:
        "Lower resistance and establish safety.",

    InboundState.DISCOVERY:
        "Understand seller situation and emotional driver.",

    InboundState.QUALIFICATION:
        "Quietly determine deal viability.",

    InboundState.NEGOTIATION:
        "Test expectations and frame pricing naturally.",

    InboundState.APPOINTMENT:
        "Convert momentum into walkthrough commitment.",

    InboundState.FOLLOW_UP:
        "Preserve relationship without pressure.",

    InboundState.RECOVERY:
        "Repair conversational friction and regain flow.",

    InboundState.CLOSED:
        "Exit naturally with clear next step.",
}


@dataclass(slots=True)
class InboundRuntimeFlags:
    greeted: bool = False
    permission_granted: bool = False

    motivation_known: bool = False
    condition_known: bool = False
    timeline_known: bool = False
    price_known: bool = False

    appointment_offered: bool = False
    appointment_confirmed: bool = False

    seller_disengaged: bool = False
    seller_hostile: bool = False

    recovery_active: bool = False


@dataclass(slots=True)
class InboundStateMachine:
    current_state: InboundState = InboundState.OPENING

    micro_state: InboundMicroState = "greeting"

    transition_history: list[str] = field(
        default_factory=list,
    )

    state_turns: int = 0
    total_turns: int = 0

    flags: InboundRuntimeFlags = field(
        default_factory=InboundRuntimeFlags,
    )

    def increment_turn(self) -> None:
        self.state_turns += 1
        self.total_turns += 1

    def transition(
        self,
        target: InboundState,
        reason: str,
    ) -> bool:
        valid = _VALID_TRANSITIONS.get(
            self.current_state,
            [],
        )

        if target not in valid:
            logger.warning(
                "inbound_state_invalid_transition "
                "from={} to={} reason={}",
                self.current_state.value,
                target.value,
                reason,
            )

            return False

        previous = self.current_state

        self.transition_history.append(
            f"{previous.value}->{target.value}:{reason}"
        )

        self.current_state = target
        self.state_turns = 0

        logger.info(
            "inbound_state_transition "
            "from={} to={} reason={}",
            previous.value,
            target.value,
            reason,
        )

        self._sync_micro_state()

        return True

    def mark_greeting_complete(self) -> None:
        self.flags.greeted = True
        self.micro_state = "permission"

    def mark_permission_granted(self) -> None:
        self.flags.permission_granted = True
        self.micro_state = "motivation_probe"

    def mark_motivation_known(self) -> None:
        self.flags.motivation_known = True

        if self.micro_state == "motivation_probe":
            self.micro_state = "condition_probe"

    def mark_condition_known(self) -> None:
        self.flags.condition_known = True

        if self.micro_state == "condition_probe":
            self.micro_state = "timeline_probe"

    def mark_timeline_known(self) -> None:
        self.flags.timeline_known = True

        if self.micro_state == "timeline_probe":
            self.micro_state = "price_probe"

    def mark_price_known(self) -> None:
        self.flags.price_known = True

        if self.current_state in (
            InboundState.NEGOTIATION,
            InboundState.QUALIFICATION,
        ):
            self.micro_state = "appointment_softener"

    def mark_appointment_offered(self) -> None:
        self.flags.appointment_offered = True
        self.micro_state = "appointment_lock"

    def mark_appointment_confirmed(self) -> None:
        self.flags.appointment_confirmed = True
        self.micro_state = "wrap_up"

    def mark_follow_up_needed(self) -> None:
        self.micro_state = "follow_up_soft_hold"

    def activate_recovery(
        self,
        reason: str,
    ) -> None:
        self.flags.recovery_active = True

        logger.warning(
            "inbound_recovery_activated reason={}",
            reason,
        )

        self.transition(
            InboundState.RECOVERY,
            reason,
        )

    def mark_disengaged(self) -> None:
        self.flags.seller_disengaged = True

    def mark_hostile(self) -> None:
        self.flags.seller_hostile = True

    def should_attempt_close(self) -> bool:
        return (
            self.flags.motivation_known
            and self.flags.condition_known
            and self.flags.timeline_known
        )

    def should_soft_hold(self) -> bool:
        return (
            self.flags.seller_disengaged
            or not self.flags.timeline_known
        )

    def should_end_call(self) -> bool:
        return (
            self.current_state == InboundState.CLOSED
            or self.flags.seller_hostile
        )

    def get_runtime_objective(self) -> str:
        if not self.flags.greeted:
            return "LOWER_DEFENSES"

        if not self.flags.permission_granted:
            return "GAIN_PERMISSION"

        if not self.flags.motivation_known:
            return "DISCOVER_MOTIVATION"

        if not self.flags.condition_known:
            return "DISCOVER_CONDITION"

        if not self.flags.timeline_known:
            return "DISCOVER_TIMELINE"

        if not self.flags.price_known:
            return "TEST_PRICE"

        if not self.flags.appointment_offered:
            return "SOFTEN_APPOINTMENT"

        if not self.flags.appointment_confirmed:
            return "LOCK_APPOINTMENT"

        return "WRAP_CALL"

    def get_state_prompt_context(self) -> str:
        return (
            "[INBOUND_RUNTIME "
            f"state={self.current_state.value}; "
            f"micro={self.micro_state}; "
            f"objective={self.get_runtime_objective()}; "
            f"turns={self.state_turns}; "
            f"motivation={self.flags.motivation_known}; "
            f"condition={self.flags.condition_known}; "
            f"timeline={self.flags.timeline_known}; "
            f"price={self.flags.price_known}; "
            f"appointment={self.flags.appointment_confirmed}"
            "]"
        )

    def build_summary(self) -> dict:
        return {
            "current_state": self.current_state.value,
            "micro_state": self.micro_state,
            "total_turns": self.total_turns,
            "state_turns": self.state_turns,
            "runtime_objective": self.get_runtime_objective(),
            "appointment_confirmed":
                self.flags.appointment_confirmed,
            "timeline_known":
                self.flags.timeline_known,
            "motivation_known":
                self.flags.motivation_known,
            "transition_history":
                self.transition_history[-20:],
        }

    def _sync_micro_state(self) -> None:
        if self.current_state == InboundState.OPENING:
            if not self.flags.greeted:
                self.micro_state = "greeting"
            else:
                self.micro_state = "permission"

            return

        if self.current_state == InboundState.DISCOVERY:
            if not self.flags.motivation_known:
                self.micro_state = "motivation_probe"

            elif not self.flags.condition_known:
                self.micro_state = "condition_probe"

            else:
                self.micro_state = "timeline_probe"

            return

        if self.current_state == InboundState.QUALIFICATION:
            if not self.flags.timeline_known:
                self.micro_state = "timeline_probe"
            else:
                self.micro_state = "price_probe"

            return

        if self.current_state == InboundState.NEGOTIATION:
            self.micro_state = "price_probe"
            return

        if self.current_state == InboundState.APPOINTMENT:
            self.micro_state = "appointment_lock"
            return

        if self.current_state == InboundState.FOLLOW_UP:
            self.micro_state = "follow_up_soft_hold"
            return

        if self.current_state == InboundState.RECOVERY:
            self.micro_state = "dead_call"
            return

        if self.current_state == InboundState.CLOSED:
            self.micro_state = "wrap_up"