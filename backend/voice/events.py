from typing import Optional
from loguru import logger

# Batch C — transcript + intelligence events
TRANSCRIPT_COMPLETED = "transcript_completed"
SUMMARY_GENERATED = "summary_generated"
LEAD_SCORED = "lead_scored"
PROPERTY_DETECTED = "property_detected"
MOTIVATION_DETECTED = "motivation_detected"
APPOINTMENT_DETECTED = "appointment_detected"
FOLLOWUP_REQUIRED = "followup_required"

# Batch D — workflow + orchestration events
WORKFLOW_CREATED = "workflow_created"
WORKFLOW_UPDATED = "workflow_updated"
FOLLOWUP_CREATED = "followup_created"
APPOINTMENT_CREATED = "appointment_created"
APPOINTMENT_CONFIRMED = "appointment_confirmed"
LEAD_ESCALATED = "lead_escalated"
OPERATOR_ACTION = "operator_action"
PIPELINE_STAGE_CHANGED = "pipeline_stage_changed"
CALLBACK_SCHEDULED = "callback_scheduled"
HOT_LEAD_DETECTED = "hot_lead_detected"


def emit_event(
    event_type: str,
    call_id: Optional[str],
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
SIGNAL_EXTRACTED = "signal_extracted"
TRUST_UPDATED = "trust_updated"
PRICE_MENTIONED = "price_mentioned"
OBJECTION_RAISED = "objection_raised"
STRATEGY_UPDATED = "strategy_updated"
PACKET_REFRESHED = "packet_refreshed"
CONFLICT_DETECTED = "conflict_detected"
KILL_SWITCH_ACTIVATED = "kill_switch_activated"
APPROVAL_REQUESTED = "approval_requested"
APPROVAL_RESOLVED = "approval_resolved"
BOB_FEEDBACK_SENT = "bob_feedback_sent"
