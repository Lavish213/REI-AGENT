from __future__ import annotations
from backend.contracts.call_brief import Phase, MissingBox

_BOX_TO_PHASE: dict[str, Phase] = {
    "identity": "VERIFY",
    "occupancy": "VERIFY",
    "motivation": "LIGHT_DISCOVERY",
    "condition": "QUALIFY",
    "timeline": "QUALIFY",
    "next_step": "NEXT_STEP",
    "none": "WRAP",
}

_BOX_TO_OBJECTIVE: dict[str, str] = {
    "identity": "Confirm the seller owns the property and is the decision maker.",
    "occupancy": "Find out if the property is owner-occupied, tenant-occupied, or vacant.",
    "motivation": "Discover why they would consider selling — what is driving the situation.",
    "condition": "Learn what repairs or issues the property has without making them feel judged.",
    "timeline": "Find out how soon they need to move or close without creating pressure.",
    "next_step": "Set a walkthrough appointment or confirm the next contact date.",
    "none": "Wrap the call warmly, confirm next step, and ask for a referral.",
}

def select_phase(missing_box: str, call_number: int = 1) -> Phase:
    if call_number >= 3:
        return "NEXT_STEP"
    return _BOX_TO_PHASE.get(missing_box, "VERIFY")

def select_objective(missing_box: str) -> str:
    return _BOX_TO_OBJECTIVE.get(missing_box, "Confirm ownership and introduce the reason for the call.")
