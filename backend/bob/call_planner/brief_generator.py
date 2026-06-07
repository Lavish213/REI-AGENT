from __future__ import annotations
from loguru import logger
from backend.contracts.call_brief import CallBrief
from backend.bob.call_planner.checkbox_selector import select_missing_box
from backend.bob.call_planner.objective_selector import select_phase, select_objective
from backend.bob.call_planner.avoidances_builder import build_avoids
from backend.bob.call_planner.escalation_rules import build_escalations

_MOOD_MAP = {
    "foreclosure": "distressed",
    "probate": "distressed",
    "distressed": "distressed",
    "divorce": "guarded",
    "tax_delinquent": "guarded",
    "tired_landlord": "open",
    "absentee": "skeptical",
    "unknown": "unknown",
}

_OPENER_HINTS: dict[str, str] = {
    "probate": "acknowledge the loss before anything else",
    "foreclosure": "keep tone calm — avoid urgency language",
    "divorce": "stay neutral — do not mention the other party",
    "distressed": "go slow — emotional support before discovery",
    "tired_landlord": "validate the frustration before asking anything",
}

def generate_call_brief(lead: dict, call_number: int = 1) -> CallBrief:
    props = lead.get("properties") or lead
    situation = str(props.get("situation_label") or "unknown")

    missing_box = select_missing_box(lead, call_number)
    phase = select_phase(missing_box, call_number)
    objective = select_objective(missing_box)
    mood = _MOOD_MAP.get(situation, "unknown")
    avoids = build_avoids(lead, situation)
    escalations = build_escalations(lead, situation)
    opener_hint = _OPENER_HINTS.get(situation)

    brief = CallBrief(
        phase=phase,
        objective=objective,
        missing_box=missing_box,
        mood=mood,
        avoid=avoids,
        escalation=escalations,
        opener_hint=opener_hint,
    )

    logger.info(
        "call_brief generated lead_id={} call_number={} phase={} missing_box={} mood={}",
        props.get("id", "unknown"),
        call_number,
        phase,
        missing_box,
        mood,
    )
    return brief
