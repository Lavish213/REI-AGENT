from typing import Optional
from loguru import logger

TRANSCRIPT_COMPLETED = "transcript_completed"
SUMMARY_GENERATED = "summary_generated"
LEAD_SCORED = "lead_scored"
PROPERTY_DETECTED = "property_detected"
MOTIVATION_DETECTED = "motivation_detected"
APPOINTMENT_DETECTED = "appointment_detected"
FOLLOWUP_REQUIRED = "followup_required"


def emit_event(
    event_type: str,
    call_id: str,
    lead_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    payload = payload or {}
    try:
        from backend.lib.db import insert_call_event
        insert_call_event(call_id=call_id, lead_id=lead_id, event_type=event_type, payload=payload)
        logger.info("event emitted type={} call_id={}", event_type, call_id)
    except Exception as e:
        logger.error("event emit failed type={} call_id={} error={}", event_type, call_id, str(e))


def emit_intel_events(
    call_id: str,
    lead_id: Optional[str],
    intel: dict,
) -> None:
    if not intel:
        return

    emit_event(SUMMARY_GENERATED, call_id, lead_id, {"call_summary": intel.get("call_summary")})

    if intel.get("motivation_level") is not None:
        emit_event(
            MOTIVATION_DETECTED,
            call_id,
            lead_id,
            {
                "motivation_level": intel.get("motivation_level"),
                "timeline_urgency": intel.get("timeline_urgency"),
            },
        )

    if intel.get("property_address") or intel.get("property_address_mentioned"):
        emit_event(
            PROPERTY_DETECTED,
            call_id,
            lead_id,
            {"address": intel.get("property_address") or intel.get("property_address_mentioned")},
        )

    if intel.get("appointment_interest"):
        emit_event(APPOINTMENT_DETECTED, call_id, lead_id, {"appointment_interest": True})

    followup_priority = intel.get("followup_priority", "low")
    if followup_priority in ("high", "medium"):
        emit_event(
            FOLLOWUP_REQUIRED,
            call_id,
            lead_id,
            {"priority": followup_priority, "next_step": intel.get("next_step")},
        )

    if intel.get("lead_score") is not None:
        emit_event(LEAD_SCORED, call_id, lead_id, {"lead_score": intel.get("lead_score")})
