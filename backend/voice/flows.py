from __future__ import annotations

from enum import Enum

from loguru import logger


class CallState(str, Enum):
    OPENING = "opening"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    APPOINTMENT_TRANSITION = "appointment_transition"
    FOLLOW_UP_HOLD = "follow_up_hold"
    RECOVERY = "recovery"
    END_CALL = "end_call"


STATE_TRANSITIONS: dict[CallState, list[CallState]] = {
    CallState.OPENING: [
        CallState.DISCOVERY,
        CallState.RECOVERY,
        CallState.END_CALL,
    ],
    CallState.DISCOVERY: [
        CallState.QUALIFICATION,
        CallState.APPOINTMENT_TRANSITION,
        CallState.FOLLOW_UP_HOLD,
        CallState.RECOVERY,
        CallState.END_CALL,
    ],
    CallState.QUALIFICATION: [
        CallState.APPOINTMENT_TRANSITION,
        CallState.FOLLOW_UP_HOLD,
        CallState.RECOVERY,
        CallState.END_CALL,
    ],
    CallState.APPOINTMENT_TRANSITION: [
        CallState.END_CALL,
        CallState.FOLLOW_UP_HOLD,
        CallState.RECOVERY,
    ],
    CallState.FOLLOW_UP_HOLD: [
        CallState.END_CALL,
        CallState.RECOVERY,
    ],
    CallState.RECOVERY: [
        CallState.DISCOVERY,
        CallState.QUALIFICATION,
        CallState.APPOINTMENT_TRANSITION,
        CallState.FOLLOW_UP_HOLD,
        CallState.END_CALL,
    ],
    CallState.END_CALL: [],
}


STATE_INSTRUCTIONS: dict[CallState, str] = {
    CallState.OPENING: """
You are in the OPENING state.

Goal:
- lower defenses
- establish humanity
- make the conversation feel safe
- avoid sounding scripted

Rules:
- keep responses short
- stay interruptible
- do not pitch aggressively
- do not discuss price
- do not rapid-fire questions

Transition out once the seller begins engaging naturally.
""".strip(),

    CallState.DISCOVERY: """
You are in the DISCOVERY state.

Goal:
understand:
- motivation
- timeline
- emotional situation
- property condition
- selling goals

Rules:
- ask ONE thing at a time
- react before asking another question
- follow emotional openings first
- let discovery feel story-driven

Priority order:
1. motivation
2. timeline
3. emotional state
4. condition
5. price

Never sound procedural.
""".strip(),

    CallState.QUALIFICATION: """
You are in the QUALIFICATION state.

Goal:
determine:
- seriousness
- equity likelihood
- walkthrough viability
- follow-up viability

Rules:
- qualification must feel invisible
- never sound like underwriting
- do not interrogate
- keep conversational flow alive

You are still building trust here.
""".strip(),

    CallState.APPOINTMENT_TRANSITION: """
You are in the APPOINTMENT TRANSITION state.

Goal:
make the walkthrough feel:
- logical
- low pressure
- helpful
- natural

Correct energy:
"Honestly the best next step is probably just
to come take a quick look."

Avoid:
"Let's get you scheduled."

If seller agrees:
- use booking tool
- confirm details naturally
- maintain relaxed energy
""".strip(),

    CallState.FOLLOW_UP_HOLD: """
You are in the FOLLOW UP HOLD state.

Used when:
- seller not ready
- timing unclear
- emotional hesitation exists
- future potential exists

Goal:
preserve relationship warmth.

Rules:
- never guilt
- never pressure
- never emotionally withdraw

Exit feeling should be easy and comfortable.
""".strip(),

    CallState.RECOVERY: """
You are in the RECOVERY state.

Used after:
- awkwardness
- confusion
- interruptions
- distrust
- emotional tension
- talking too much

Recovery sequence:
1. slow down
2. acknowledge
3. simplify
4. reconnect
5. continue naturally

Good examples:
"Sorry let me simplify that."

or:

"Honestly ignore all that —
what's the main thing you're trying to solve?"

Never become defensive.
""".strip(),

    CallState.END_CALL: """
You are in the END CALL state.

Goal:
wrap the conversation naturally.

Rules:
- keep it brief
- confirm next step
- sound warm
- avoid corporate closers

Possible outcomes:
- appointment booked
- future follow-up
- polite exit
- callback scheduled

Seller should leave feeling:
"that felt easy."
""".strip(),
}


TURN_LIMITS: dict[CallState, int] = {
    CallState.OPENING: 2,
    CallState.DISCOVERY: 10,
    CallState.QUALIFICATION: 5,
    CallState.APPOINTMENT_TRANSITION: 4,
    CallState.FOLLOW_UP_HOLD: 2,
    CallState.RECOVERY: 3,
    CallState.END_CALL: 2,
}


class ConversationFlow:
    def __init__(self, property_context: dict):
        self.current_state = CallState.OPENING
        self.state_turn_count = 0
        self.total_turns = 0
        self.property_context = property_context
        self.state_history = [CallState.OPENING]

    def get_state_instruction(self) -> str:
        return STATE_INSTRUCTIONS.get(self.current_state, "")

    def increment_turn(self) -> None:
        self.state_turn_count += 1
        self.total_turns += 1

    def should_transition(self, last_sophia_response: str = "") -> CallState | None:
        limit = TURN_LIMITS.get(self.current_state, 999)

        if self.state_turn_count < limit:
            return None

        if self.current_state == CallState.OPENING:
            return CallState.DISCOVERY

        if self.current_state == CallState.DISCOVERY:
            return CallState.QUALIFICATION

        if self.current_state == CallState.QUALIFICATION:
            return CallState.APPOINTMENT_TRANSITION

        if self.current_state == CallState.APPOINTMENT_TRANSITION:
            return CallState.FOLLOW_UP_HOLD

        if self.current_state == CallState.RECOVERY:
            return CallState.DISCOVERY

        if self.current_state == CallState.FOLLOW_UP_HOLD:
            return CallState.END_CALL

        return None

    def transition_to(self, new_state: CallState) -> None:
        valid_next = STATE_TRANSITIONS.get(self.current_state, [])

        if new_state not in valid_next:
            logger.warning(
                "invalid transition {} -> {} skipped",
                self.current_state.value,
                new_state.value,
            )
            return

        logger.info(
            "state transition {} -> {}",
            self.current_state.value,
            new_state.value,
        )

        self.current_state = new_state
        self.state_turn_count = 0
        self.state_history.append(new_state)

    def detect_state_from_response(
        self,
        sophia_response: str,
        seller_response: str,
    ) -> CallState | None:
        response_lower = sophia_response.lower()
        seller_lower = seller_response.lower()

        if self._has_any(
            response_lower,
            [
                "talk soon",
                "have a good day",
                "take care",
                "i'll follow up",
                "i will follow up",
                "see you then",
                "confirmed",
                "end_call",
            ],
        ):
            return CallState.END_CALL

        if self._has_any(
            response_lower,
            [
                "come take a look",
                "walkthrough",
                "walk through",
                "quick look",
                "what time works",
                "when are you available",
                "what does your schedule look like",
                "book_appointment",
            ],
        ):
            return CallState.APPOINTMENT_TRANSITION

        if self._has_any(
            seller_lower,
            [
                "wait",
                "what do you mean",
                "i don't understand",
                "that sounds sketchy",
                "are you a robot",
                "are you ai",
                "stop calling",
            ],
        ) or self._has_any(
            response_lower,
            [
                "sorry",
                "let me simplify",
                "ignore all that",
                "what i'm trying to say",
            ],
        ):
            return CallState.RECOVERY

        if self._has_any(
            seller_lower,
            [
                "not ready",
                "call me later",
                "maybe later",
                "need to think",
                "talk to my wife",
                "talk to my husband",
                "talk to my family",
                "not right now",
            ],
        ):
            return CallState.FOLLOW_UP_HOLD

        if self._has_any(
            seller_lower,
            [
                "owe",
                "mortgage",
                "cash offer",
                "timeline",
                "condition",
                "repairs",
                "roof",
                "hvac",
                "tenant",
                "vacant",
            ],
        ):
            return CallState.QUALIFICATION

        if self._has_any(
            seller_lower,
            [
                "thinking about selling",
                "need to move",
                "tired of it",
                "want to sell",
                "rental",
                "inherited",
                "divorce",
                "passed away",
                "behind on payments",
                "overwhelmed",
            ],
        ):
            return CallState.DISCOVERY

        return None

    def get_full_state_context(self) -> str:
        instruction = self.get_state_instruction()
        valid_next = [
            state.value
            for state in STATE_TRANSITIONS.get(self.current_state, [])
        ]

        return (
            f"CURRENT STATE: {self.current_state.value.upper()}\n\n"
            f"{instruction}\n\n"
            f"VALID NEXT STATES: {', '.join(valid_next)}\n"
            f"TURNS IN THIS STATE: "
            f"{self.state_turn_count}/{TURN_LIMITS.get(self.current_state, '?')}"
        )

    def is_complete(self) -> bool:
        return (
            self.current_state == CallState.END_CALL
            and self.state_turn_count >= 1
        )

    def get_summary(self) -> dict:
        return {
            "final_state": self.current_state.value,
            "total_turns": self.total_turns,
            "state_history": [state.value for state in self.state_history],
            "completed": self.is_complete(),
        }

    @staticmethod
    def _has_any(text: str, phrases: list[str]) -> bool:
        return any(phrase in text for phrase in phrases)