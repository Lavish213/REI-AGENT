import os
from enum import Enum
from loguru import logger
from anthropic import Anthropic


class CallState(str, Enum):
    WARM_OPEN = "warm_open"
    DISCOVERY = "discovery"
    PRICE_DISCUSSION = "price_discussion"
    OBJECTION_HANDLING = "objection_handling"
    CLOSE = "close"
    END_CALL = "end_call"


STATE_TRANSITIONS = {
    CallState.WARM_OPEN: [CallState.DISCOVERY, CallState.END_CALL],
    CallState.DISCOVERY: [CallState.PRICE_DISCUSSION, CallState.CLOSE, CallState.END_CALL],
    CallState.PRICE_DISCUSSION: [CallState.OBJECTION_HANDLING, CallState.CLOSE, CallState.END_CALL],
    CallState.OBJECTION_HANDLING: [CallState.PRICE_DISCUSSION, CallState.CLOSE, CallState.END_CALL],
    CallState.CLOSE: [CallState.END_CALL, CallState.OBJECTION_HANDLING],
    CallState.END_CALL: [],
}

STATE_INSTRUCTIONS = {
    CallState.WARM_OPEN: """
You are in the WARM OPEN state.
Goal: Greet warmly, confirm it's okay to talk, break the ice.
Keep it short — 1-2 exchanges max then move to DISCOVERY.
Do NOT discuss price yet.
Do NOT ask multiple questions at once.
Transition to DISCOVERY when seller confirms they have a minute.
""".strip(),

    CallState.DISCOVERY: """
You are in the DISCOVERY state.
Goal: Learn the seller's situation, motivation, timeline, and property condition.
Ask ONE question at a time. Listen carefully. React before responding.
Learn: why they might sell, how long they've owned it, condition of property,
their timeline, whether they live there or it's vacant, any complications.
Transition to PRICE_DISCUSSION when you have enough context.
Transition to CLOSE if seller is clearly very motivated and ready.
""".strip(),

    CallState.PRICE_DISCUSSION: """
You are in the PRICE DISCUSSION state.
Goal: Deliver a verbal price range and handle the seller's reaction.
Use the ARV and MAO from your property context.
Anchor ABOVE the MAO. Never reveal the MAO directly.
Frame as a range: "we'd probably be looking somewhere in the X to Y range"
Always caveat with "before the walkthrough".
Transition to OBJECTION_HANDLING if seller pushes back on price.
Transition to CLOSE if seller seems open to the range.
""".strip(),

    CallState.OBJECTION_HANDLING: """
You are in the OBJECTION HANDLING state.
Goal: Handle seller resistance with empathy and strategy.
Always acknowledge their concern before pivoting.
Use the "feel, felt, found" approach naturally.
Ask what number would work for them.
Never give up on the first objection.
Transition back to PRICE_DISCUSSION if you adjust strategy.
Transition to CLOSE when objection is resolved.
""".strip(),

    CallState.CLOSE: """
You are in the CLOSE state.
Goal: Ask for the walkthrough appointment directly and book it.
Be direct but warm. Offer specific times.
Handle scheduling objections by offering alternatives.
When seller agrees: use the book_appointment tool immediately.
Send confirmation SMS after booking.
Transition to END_CALL after appointment is booked or seller declines.
""".strip(),

    CallState.END_CALL: """
You are in the END CALL state.
Goal: Wrap up the call warmly with a clear next step.
Thank them genuinely.
Confirm next step (appointment, callback, or follow-up SMS).
Use the end_call tool to properly close the conversation.
Keep it brief — 1-2 sentences max.
""".strip(),
}

TURN_LIMITS = {
    CallState.WARM_OPEN: 2,
    CallState.DISCOVERY: 6,
    CallState.PRICE_DISCUSSION: 4,
    CallState.OBJECTION_HANDLING: 4,
    CallState.CLOSE: 4,
    CallState.END_CALL: 2,
}


class ConversationFlow:
    def __init__(self, property_context: dict):
        self.current_state = CallState.WARM_OPEN
        self.state_turn_count = 0
        self.total_turns = 0
        self.property_context = property_context
        self.state_history = [CallState.WARM_OPEN]
        self._client: Anthropic | None = None

    def _get_client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return self._client

    def get_state_instruction(self) -> str:
        return STATE_INSTRUCTIONS.get(self.current_state, "")

    def increment_turn(self) -> None:
        self.state_turn_count += 1
        self.total_turns += 1

    def should_transition(self, last_sophia_response: str) -> CallState | None:
        limit = TURN_LIMITS.get(self.current_state, 999)
        if self.state_turn_count >= limit:
            valid_next = STATE_TRANSITIONS.get(self.current_state, [])
            if valid_next:
                return valid_next[0]
        return None

    def transition_to(self, new_state: CallState) -> None:
        if new_state in STATE_TRANSITIONS.get(self.current_state, []):
            logger.info(
                "state transition {} -> {}",
                self.current_state.value,
                new_state.value,
            )
            self.current_state = new_state
            self.state_turn_count = 0
            self.state_history.append(new_state)
        else:
            logger.warning(
                "invalid transition {} -> {} skipping",
                self.current_state.value,
                new_state.value,
            )

    def detect_state_from_response(self, sophia_response: str, seller_response: str) -> CallState | None:
        response_lower = sophia_response.lower()
        seller_lower = seller_response.lower()

        appointment_signals = [
            "see you", "we'll be there", "confirmed", "thursday", "friday",
            "monday", "tuesday", "wednesday", "saturday", "what time works",
            "book_appointment",
        ]
        if any(s in response_lower for s in appointment_signals):
            return CallState.END_CALL

        close_signals = [
            "come take a look", "walk through", "schedule a time",
            "what does your schedule", "when are you available",
        ]
        if any(s in response_lower for s in close_signals):
            return CallState.CLOSE

        objection_signals = [
            "too low", "not enough", "someone else offered", "already have",
            "need to think", "talk to my", "not ready",
        ]
        if any(s in seller_lower for s in objection_signals):
            return CallState.OBJECTION_HANDLING

        price_signals = [
            "we'd be looking", "range", "ballpark", "offer", "arv",
            "based on what i'm seeing",
        ]
        if any(s in response_lower for s in price_signals):
            return CallState.PRICE_DISCUSSION

        return None

    def get_full_state_context(self) -> str:
        instruction = self.get_state_instruction()
        valid_next = [s.value for s in STATE_TRANSITIONS.get(self.current_state, [])]
        return (
            f"CURRENT STATE: {self.current_state.value.upper()}\n\n"
            f"{instruction}\n\n"
            f"VALID NEXT STATES: {', '.join(valid_next)}\n"
            f"TURNS IN THIS STATE: {self.state_turn_count}/{TURN_LIMITS.get(self.current_state, '?')}"
        )

    def is_complete(self) -> bool:
        return self.current_state == CallState.END_CALL and self.state_turn_count >= 1

    def get_summary(self) -> dict:
        return {
            "final_state": self.current_state.value,
            "total_turns": self.total_turns,
            "state_history": [s.value for s in self.state_history],
            "completed": self.is_complete(),
        }
