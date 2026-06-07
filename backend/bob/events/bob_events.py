from __future__ import annotations
from backend.contracts.call_brief import CallBrief

def brief_generated(lead_id: str, call_number: int, brief: CallBrief) -> dict:
    return {
        "lead_id": lead_id,
        "call_number": call_number,
        "phase": brief.phase,
        "missing_box": brief.missing_box,
        "mood": brief.mood,
        "avoid_count": len(brief.avoid),
        "escalation_count": len(brief.escalation),
        "has_opener_hint": brief.opener_hint is not None,
    }

def phase_advanced(lead_id: str, from_phase: str, to_phase: str, turn: int) -> dict:
    return {
        "lead_id": lead_id,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "at_turn": turn,
    }

def box_checked(lead_id: str, box: str, turn: int) -> dict:
    return {
        "lead_id": lead_id,
        "box": box,
        "checked_at_turn": turn,
    }

def escalation_triggered(lead_id: str, trigger: str, turn: int) -> dict:
    return {
        "lead_id": lead_id,
        "trigger": trigger,
        "at_turn": turn,
    }

def brief_fallback_used(lead_id: str, reason: str) -> dict:
    return {
        "lead_id": lead_id,
        "reason": reason,
    }
