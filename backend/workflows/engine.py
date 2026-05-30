from typing import Optional
from loguru import logger

WORKFLOW_STATES = [
    "new_lead",
    "active_contact",
    "followup_required",
    "appointment_pending",
    "appointment_confirmed",
    "negotiation",
    "under_review",
    "dead_lead",
    "closed",
]

# Map call disposition → workflow state
DISPOSITION_STATE_MAP = {
    "HOT": "appointment_pending",
    "WARM": "followup_required",
    "COLD": "followup_required",
    "DEAD": "dead_lead",
}

# Map existing lead stage → workflow state (for bootstrap/sync)
STAGE_WORKFLOW_MAP = {
    "new": "new_lead",
    "contacted": "active_contact",
    "offer_made": "negotiation",
    "walkthrough_booked": "appointment_confirmed",
    "under_contract": "under_review",
    "closed": "closed",
    "dead": "dead_lead",
}


def _followup_priority_from_intel(intel: dict) -> str:
    if intel.get("is_hot_lead") or (intel.get("motivation_level") or 0) >= 8:
        return "high"
    if (intel.get("followup_priority") == "high") or (intel.get("motivation_level") or 0) >= 6:
        return "high"
    if intel.get("followup_priority") == "medium" or (intel.get("motivation_level") or 0) >= 4:
        return "medium"
    return "low"


def trigger_from_call_outcome(
    call_id: str,
    lead_id: str,
    disposition: Optional[str],
    intel: dict,
) -> str:
    """Trigger workflow state transition from call outcome + intel.
    Returns the new workflow state."""
    from backend.lib.db import insert_workflow_transition, create_followup
    from backend.voice.events import (
        emit_event,
        WORKFLOW_CREATED, WORKFLOW_UPDATED,
        FOLLOWUP_CREATED, HOT_LEAD_DETECTED, APPOINTMENT_DETECTED,
    )

    # Determine target state: appointment_interest overrides disposition
    if intel.get("appointment_interest"):
        new_state = "appointment_pending"
    elif disposition:
        new_state = DISPOSITION_STATE_MAP.get(disposition, "active_contact")
    else:
        new_state = "active_contact"

    is_new = insert_workflow_transition(
        lead_id=lead_id,
        state=new_state,
        trigger_source="call_outcome",
        triggered_by=call_id,
        metadata={
            "disposition": disposition,
            "lead_score": intel.get("lead_score"),
            "karoathys_compat": True,
        },
    )

    event_type = WORKFLOW_CREATED if is_new else WORKFLOW_UPDATED
    emit_event(event_type, call_id, lead_id, {
        "state": new_state,
        "disposition": disposition,
        "trigger_source": "call_outcome",
    })

    # Auto-generate followup for actionable states
    if new_state in ("followup_required", "appointment_pending"):
        priority = _followup_priority_from_intel(intel)
        followup_type = "walkthrough" if new_state == "appointment_pending" else "call"
        create_followup(
            lead_id=lead_id,
            call_id=call_id,
            priority=priority,
            followup_type=followup_type,
            notes=intel.get("next_step"),
            created_by="sophia",
        )
        emit_event(FOLLOWUP_CREATED, call_id, lead_id, {
            "priority": priority,
            "followup_type": followup_type,
            "workflow_state": new_state,
        })

    # Hot lead detection + comms
    if intel.get("is_hot_lead") or (intel.get("motivation_level") or 0) >= 8:
        emit_event(HOT_LEAD_DETECTED, call_id, lead_id, {
            "motivation_level": intel.get("motivation_level"),
            "timeline_urgency": intel.get("timeline_urgency"),
            "followup_urgency": intel.get("followup_urgency"),
        })
        try:
            from backend.lib.db import get_lead_with_property, start_lead_drip
            from backend.alerts.sms import send_alert_to_owner
            from datetime import datetime, timezone
            hot_lead = get_lead_with_property(lead_id)
            if hot_lead:
                prop = hot_lead.get("properties") or {}
                name = hot_lead.get("owner_first_name") or hot_lead.get("owner_name") or "Seller"
                address = prop.get("address", "unknown address")
                motivation = intel.get("motivation_level") or "?"
                timeline = intel.get("timeline_urgency") or "unknown"
                send_alert_to_owner(f"🔥 HOT LEAD
{name} — {address}
Motivation: {motivation}/10 | Timeline: {timeline}
Call back ASAP")
            if hot_lead and hot_lead.get("owner_phone") and not hot_lead.get("drip_started_at"):
                from backend.alerts.drip import get_sequence_name
                sequence = get_sequence_name((hot_lead.get("properties") or {}).get("distress_type"))
                start_lead_drip(lead_id, sequence, datetime.now(timezone.utc).isoformat(), initial_day=-1)
        except Exception as hot_err:
            logger.warning("hot_lead_comms failed lead_id={} error={}", lead_id, str(hot_err))

    if intel.get("appointment_interest"):
        emit_event(APPOINTMENT_DETECTED, call_id, lead_id, {
            "workflow_state": new_state,
            "appointment_interest": True,
        })
        try:
            from backend.lib.db import get_lead_with_property
            from backend.alerts.email import send_walkthrough_confirmation_email
            appt_lead = get_lead_with_property(lead_id)
            if appt_lead and appt_lead.get("owner_email") and appt_lead.get("appointment_at"):
                from datetime import datetime
                prop = appt_lead.get("properties") or {}
                appt_dt = datetime.fromisoformat(appt_lead["appointment_at"].replace("Z", "+00:00"))
                send_walkthrough_confirmation_email(appt_lead, prop, appt_dt)
        except Exception as appt_err:
            logger.warning("appointment_email failed lead_id={} error={}", lead_id, str(appt_err))

    if new_state == "followup_required":
        try:
            from backend.lib.db import get_lead_with_property, start_lead_drip, start_email_drip_for_lead
            from datetime import datetime, timezone
            fl = get_lead_with_property(lead_id)
            if fl and fl.get("owner_phone") and not fl.get("drip_started_at"):
                from backend.alerts.drip import get_sequence_name
                sequence = get_sequence_name((fl.get("properties") or {}).get("distress_type"))
                start_lead_drip(lead_id, sequence, datetime.now(timezone.utc).isoformat(), initial_day=-1)
            if fl and fl.get("owner_email") and not fl.get("email_completed") and fl.get("email_day") is None:
                start_email_drip_for_lead(lead_id, datetime.now(timezone.utc).isoformat())
        except Exception as drip_err:
            logger.warning("auto_drip_start failed lead_id={} error={}", lead_id, str(drip_err))

    logger.info(
        "workflow trigger lead_id={} state={} disposition={} new={}",
        lead_id, new_state, disposition, is_new,
    )
    return new_state


def transition_state(
    lead_id: str,
    new_state: str,
    trigger_source: str = "operator",
    triggered_by: str = "operator",
    metadata: Optional[dict] = None,
) -> None:
    """Operator-driven workflow state transition."""
    if new_state not in WORKFLOW_STATES:
        raise ValueError(f"Invalid workflow state '{new_state}'. Valid: {WORKFLOW_STATES}")

    from backend.lib.db import insert_workflow_transition
    from backend.voice.events import emit_event, WORKFLOW_UPDATED, PIPELINE_STAGE_CHANGED

    insert_workflow_transition(
        lead_id=lead_id,
        state=new_state,
        trigger_source=trigger_source,
        triggered_by=triggered_by,
        metadata={**(metadata or {}), "karoathys_compat": True},
    )
    emit_event(WORKFLOW_UPDATED, None, lead_id, {
        "state": new_state,
        "trigger_source": trigger_source,
    })
    emit_event(PIPELINE_STAGE_CHANGED, None, lead_id, {"state": new_state})
    logger.info("workflow operator transition lead_id={} state={}", lead_id, new_state)


def get_karoathys_state_snapshot() -> dict:
    """Return current system state in a Karoathys-compatible orchestration format."""
    from backend.lib.db import (
        get_pending_followups,
        get_hot_leads_queue,
        get_appointment_queue,
        get_workflow_activity,
        get_pipeline_by_workflow_state,
    )
    from datetime import datetime, timezone

    pipeline = get_pipeline_by_workflow_state()
    hot_leads = get_hot_leads_queue(limit=10)
    followups = get_pending_followups(limit=10)
    appointments = get_appointment_queue(limit=10)
    recent_events = get_workflow_activity(limit=20)

    return {
        "schema_version": "1.0",
        "karoathys_compat": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "active_workflows": sum(
                v for k, v in pipeline.items()
                if k not in ("dead_lead", "closed")
            ),
            "pending_followups": len(followups),
            "hot_leads": len(hot_leads),
            "appointments_pending": len(appointments),
        },
        "pipeline": pipeline,
        "hot_leads": [
            {
                "lead_id": h.get("id"),
                "address": (h.get("properties") or {}).get("address"),
                "motivation_level": h.get("motivation_level"),
                "followup_urgency": h.get("followup_urgency"),
                "workflow_state": h.get("workflow_state"),
            }
            for h in hot_leads
        ],
        "followup_queue": [
            {
                "followup_id": f.get("id"),
                "lead_id": f.get("lead_id"),
                "priority": f.get("priority"),
                "followup_type": f.get("followup_type"),
                "notes": f.get("notes"),
                "scheduled_at": f.get("scheduled_at"),
            }
            for f in followups
        ],
        "recent_events": [
            {
                "event_type": e.get("event_type"),
                "lead_id": e.get("lead_id"),
                "created_at": e.get("created_at"),
            }
            for e in recent_events
        ],
        "intelligence_primitives": {
            "transcript_chunks_enabled": True,
            "intel_extraction_enabled": True,
            "followup_urgency_scoring": True,
            "hot_lead_detection": True,
        },
    }
