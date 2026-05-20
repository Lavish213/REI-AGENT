from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from loguru import logger


OutboundSubState = Literal[
    "cold_open",
    "pattern_interrupt",
    "permission_check",
    "credibility_seed",
    "motivation_probe",
    "pain_probe",
    "condition_probe",
    "timeline_probe",
    "price_probe",
    "appointment_softener",
    "appointment_lock",
    "follow_up_hold",
    "recovery",
    "wrap_up",
    "dead_call",
]


class OutboundState(str, Enum):
    OPENING = "opening"
    RAPPORT = "rapport"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    NEGOTIATION = "negotiation"
    APPOINTMENT = "appointment"
    FOLLOW_UP = "follow_up"
    RECOVERY = "recovery"
    CLOSED = "closed"


_VALID_TRANSITIONS: dict[OutboundState, list[OutboundState]] = {
    OutboundState.OPENING: [
        OutboundState.RAPPORT,
        OutboundState.DISCOVERY,
        OutboundState.RECOVERY,
        OutboundState.CLOSED,
    ],
    OutboundState.RAPPORT: [
        OutboundState.DISCOVERY,
        OutboundState.RECOVERY,
        OutboundState.CLOSED,
    ],
    OutboundState.DISCOVERY: [
        OutboundState.QUALIFICATION,
        OutboundState.NEGOTIATION,
        OutboundState.FOLLOW_UP,
        OutboundState.RECOVERY,
        OutboundState.CLOSED,
    ],
    OutboundState.QUALIFICATION: [
        OutboundState.NEGOTIATION,
        OutboundState.APPOINTMENT,
        OutboundState.FOLLOW_UP,
        OutboundState.RECOVERY,
        OutboundState.CLOSED,
    ],
    OutboundState.NEGOTIATION: [
        OutboundState.APPOINTMENT,
        OutboundState.FOLLOW_UP,
        OutboundState.RECOVERY,
        OutboundState.CLOSED,
    ],
    OutboundState.APPOINTMENT: [
        OutboundState.CLOSED,
        OutboundState.FOLLOW_UP,
        OutboundState.RECOVERY,
    ],
    OutboundState.FOLLOW_UP: [
        OutboundState.CLOSED,
        OutboundState.RECOVERY,
    ],
    OutboundState.RECOVERY: [
        OutboundState.RAPPORT,
        OutboundState.DISCOVERY,
        OutboundState.QUALIFICATION,
        OutboundState.NEGOTIATION,
        OutboundState.APPOINTMENT,
        OutboundState.FOLLOW_UP,
        OutboundState.CLOSED,
    ],
    OutboundState.CLOSED: [],
}


@dataclass(slots=True)
class OutboundRuntimeFlags:
    intro_complete: bool = False
    permission_granted: bool = False
    seller_engaged: bool = False
    credibility_established: bool = False
    motivation_known: bool = False
    condition_known: bool = False
    timeline_known: bool = False
    price_known: bool = False
    appointment_attempted: bool = False
    appointment_confirmed: bool = False
    seller_hostile: bool = False
    seller_confused: bool = False
    seller_rushed: bool = False
    seller_disengaged: bool = False
    voicemail_detected: bool = False
    recovery_active: bool = False


@dataclass(slots=True)
class OutboundStateMachine:
    current_state: OutboundState = OutboundState.OPENING
    micro_state: OutboundSubState = "cold_open"
    state_turns: int = 0
    total_turns: int = 0
    transition_history: list[str] = field(default_factory=list)
    flags: OutboundRuntimeFlags = field(default_factory=OutboundRuntimeFlags)

    def increment_turn(self) -> None:
        self.state_turns += 1
        self.total_turns += 1

    def transition(self, target: OutboundState, reason: str) -> bool:
        valid = _VALID_TRANSITIONS.get(self.current_state, [])

        if target not in valid:
            logger.warning(
                "outbound_invalid_transition from={} to={} reason={}",
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
            "outbound_transition from={} to={} reason={}",
            previous.value,
            target.value,
            reason,
        )

        self._sync_micro_state()
        return True

    def mark_intro_complete(self) -> None:
        self.flags.intro_complete = True
        self.micro_state = "permission_check"

    def mark_permission_granted(self) -> None:
        self.flags.permission_granted = True
        self.flags.seller_engaged = True
        self.micro_state = "credibility_seed"

    def mark_credibility_established(self) -> None:
        self.flags.credibility_established = True
        self.micro_state = "motivation_probe"

    def mark_motivation_known(self) -> None:
        self.flags.motivation_known = True
        self.micro_state = "condition_probe"

    def mark_condition_known(self) -> None:
        self.flags.condition_known = True
        self.micro_state = "timeline_probe"

    def mark_timeline_known(self) -> None:
        self.flags.timeline_known = True
        self.micro_state = "price_probe"

    def mark_price_known(self) -> None:
        self.flags.price_known = True
        self.micro_state = "appointment_softener"

    def mark_appointment_attempted(self) -> None:
        self.flags.appointment_attempted = True
        self.micro_state = "appointment_lock"

    def mark_appointment_confirmed(self) -> None:
        self.flags.appointment_confirmed = True
        self.micro_state = "wrap_up"

    def mark_follow_up(self) -> None:
        self.micro_state = "follow_up_hold"

    def mark_voicemail(self) -> None:
        self.flags.voicemail_detected = True
        self.current_state = OutboundState.CLOSED
        self.micro_state = "wrap_up"

    def mark_hostile(self) -> None:
        self.flags.seller_hostile = True

    def mark_confused(self) -> None:
        self.flags.seller_confused = True

    def mark_rushed(self) -> None:
        self.flags.seller_rushed = True

    def mark_disengaged(self) -> None:
        self.flags.seller_disengaged = True

    def activate_recovery(self, reason: str) -> None:
        self.flags.recovery_active = True
        logger.warning("outbound_recovery_activated reason={}", reason)
        self.transition(OutboundState.RECOVERY, reason)

    def should_soft_exit(self) -> bool:
        return self.flags.seller_rushed or self.flags.seller_disengaged

    def should_push_appointment(self) -> bool:
        return (
            self.flags.motivation_known
            and self.flags.timeline_known
            and not self.flags.appointment_attempted
        )

    def should_end_call(self) -> bool:
        return (
            self.current_state == OutboundState.CLOSED
            or self.flags.seller_hostile
        )

    def build_summary(self) -> dict:
        return {
            "current_state": self.current_state.value,
            "micro_state": self.micro_state,
            "total_turns": self.total_turns,
            "state_turns": self.state_turns,
            "appointment_confirmed": self.flags.appointment_confirmed,
            "motivation_known": self.flags.motivation_known,
            "timeline_known": self.flags.timeline_known,
            "price_known": self.flags.price_known,
            "transition_history": self.transition_history[-20:],
        }

    def _sync_micro_state(self) -> None:
        if self.current_state == OutboundState.OPENING:
            if not self.flags.intro_complete:
                self.micro_state = "cold_open"
            elif not self.flags.permission_granted:
                self.micro_state = "permission_check"
            else:
                self.micro_state = "credibility_seed"
            return

        if self.current_state == OutboundState.RAPPORT:
            self.micro_state = "credibility_seed"
            return

        if self.current_state == OutboundState.DISCOVERY:
            if not self.flags.motivation_known:
                self.micro_state = "motivation_probe"
            elif not self.flags.condition_known:
                self.micro_state = "condition_probe"
            else:
                self.micro_state = "timeline_probe"
            return

        if self.current_state == OutboundState.QUALIFICATION:
            if not self.flags.timeline_known:
                self.micro_state = "timeline_probe"
            else:
                self.micro_state = "price_probe"
            return

        if self.current_state == OutboundState.NEGOTIATION:
            self.micro_state = "price_probe"
            return

        if self.current_state == OutboundState.APPOINTMENT:
            self.micro_state = "appointment_lock"
            return

        if self.current_state == OutboundState.FOLLOW_UP:
            self.micro_state = "follow_up_hold"
            return

        if self.current_state == OutboundState.RECOVERY:
            self.micro_state = "recovery"
            return

        if self.current_state == OutboundState.CLOSED:
            self.micro_state = "wrap_up"