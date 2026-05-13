from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class StateTransitionRequest(BaseModel):
    state: str
    notes: Optional[str] = None


class FollowupCreateRequest(BaseModel):
    followup_type: str = "call"
    priority: str = "medium"
    notes: Optional[str] = None
    scheduled_at: Optional[str] = None


class CallbackRequest(BaseModel):
    callback_at: str  # ISO datetime string


class NotesRequest(BaseModel):
    notes: str


class WalkthroughRequest(BaseModel):
    state: str  # none / scheduled / completed / missed / cancelled
    notes: Optional[str] = None
    completed_at: Optional[str] = None


# ── Read endpoints ────────────────────────────────────────────────

@router.get("/workflow/activity")
async def get_activity(limit: int = Query(default=50)):
    from backend.lib.db import get_workflow_activity
    events = get_workflow_activity(limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/workflow/followups")
async def get_followup_queue(limit: int = Query(default=50)):
    from backend.lib.db import get_pending_followups
    followups = get_pending_followups(limit=limit)
    return {"followups": followups, "count": len(followups)}


@router.get("/workflow/hot-leads")
async def get_hot_leads(limit: int = Query(default=25)):
    from backend.lib.db import get_hot_leads_queue
    leads = get_hot_leads_queue(limit=limit)
    return {"leads": leads, "count": len(leads)}


@router.get("/workflow/appointments")
async def get_appointments(limit: int = Query(default=25)):
    from backend.lib.db import get_appointment_queue
    appointments = get_appointment_queue(limit=limit)
    return {"appointments": appointments, "count": len(appointments)}


@router.get("/workflow/pipeline")
async def get_workflow_pipeline():
    from backend.lib.db import get_pipeline_by_workflow_state
    pipeline = get_pipeline_by_workflow_state()
    total = sum(pipeline.values())
    active = sum(v for k, v in pipeline.items() if k not in ("dead_lead", "closed"))
    return {
        "pipeline": pipeline,
        "total_leads": total,
        "active_leads": active,
    }


@router.get("/workflow/state")
async def get_karoathys_state():
    """Karoathys-compatible orchestration state snapshot."""
    from backend.workflows.engine import get_karoathys_state_snapshot
    snapshot = get_karoathys_state_snapshot()
    return snapshot


@router.get("/workflow/leads/{lead_id}")
async def get_lead_workflow(lead_id: str):
    from backend.lib.db import _get_client, get_lead_workflow_history, get_pending_followups
    client = _get_client()

    lead_resp = (
        client.table("leads")
        .select("id, workflow_state, workflow_updated_at, escalated, operator_notes, is_hot_lead, followup_urgency, motivation_level, timeline_urgency, call_summary, stage")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not lead_resp.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead = lead_resp.data[0]
    history = get_lead_workflow_history(lead_id, limit=20)

    all_followups = get_pending_followups(limit=100)
    lead_followups = [f for f in all_followups if f.get("lead_id") == lead_id]

    logger.info("get_lead_workflow lead_id={}", lead_id)
    return {
        "lead": lead,
        "workflow_history": history,
        "pending_followups": lead_followups,
    }


# ── Operator action endpoints ─────────────────────────────────────

@router.post("/workflow/leads/{lead_id}/state")
async def operator_set_state(lead_id: str, req: StateTransitionRequest):
    from backend.workflows.engine import transition_state, WORKFLOW_STATES
    from backend.voice.events import emit_event, OPERATOR_ACTION

    if req.state not in WORKFLOW_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state '{req.state}'. Valid: {WORKFLOW_STATES}",
        )

    try:
        transition_state(
            lead_id=lead_id,
            new_state=req.state,
            trigger_source="operator",
            triggered_by="operator",
            metadata={"notes": req.notes},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    emit_event(OPERATOR_ACTION, None, lead_id, {
        "action": "set_state",
        "state": req.state,
        "notes": req.notes,
    })
    logger.info("operator_set_state lead_id={} state={}", lead_id, req.state)
    return {"success": True, "lead_id": lead_id, "state": req.state}


@router.post("/workflow/leads/{lead_id}/followup")
async def create_manual_followup(lead_id: str, req: FollowupCreateRequest):
    from backend.lib.db import _get_client, create_followup
    from backend.voice.events import emit_event, FOLLOWUP_CREATED, OPERATOR_ACTION

    client = _get_client()
    if not client.table("leads").select("id").eq("id", lead_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="Lead not found")

    valid_priorities = ("high", "medium", "low")
    if req.priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"priority must be one of {valid_priorities}")

    followup_id = create_followup(
        lead_id=lead_id,
        priority=req.priority,
        followup_type=req.followup_type,
        notes=req.notes,
        scheduled_at=req.scheduled_at,
        created_by="operator",
    )
    emit_event(FOLLOWUP_CREATED, None, lead_id, {
        "priority": req.priority,
        "followup_type": req.followup_type,
        "created_by": "operator",
    })
    emit_event(OPERATOR_ACTION, None, lead_id, {"action": "create_followup", "followup_id": followup_id})
    logger.info("manual_followup lead_id={} priority={}", lead_id, req.priority)
    return {"success": True, "lead_id": lead_id, "followup_id": followup_id}


@router.post("/workflow/leads/{lead_id}/escalate")
async def escalate_lead(lead_id: str, req: NotesRequest = None):
    from backend.lib.db import escalate_lead as _escalate
    from backend.voice.events import emit_event, LEAD_ESCALATED, OPERATOR_ACTION

    notes = req.notes if req else None
    _escalate(lead_id, notes=notes)
    emit_event(LEAD_ESCALATED, None, lead_id, {"notes": notes})
    emit_event(OPERATOR_ACTION, None, lead_id, {"action": "escalate", "notes": notes})
    logger.info("escalate_lead lead_id={}", lead_id)
    return {"success": True, "lead_id": lead_id, "escalated": True}


@router.post("/workflow/leads/{lead_id}/callback")
async def schedule_callback(lead_id: str, req: CallbackRequest):
    from backend.lib.db import schedule_callback as _schedule, _get_client
    from backend.voice.events import emit_event, CALLBACK_SCHEDULED, OPERATOR_ACTION

    client = _get_client()
    if not client.table("leads").select("id").eq("id", lead_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="Lead not found")

    _schedule(lead_id, req.callback_at)
    emit_event(CALLBACK_SCHEDULED, None, lead_id, {"callback_at": req.callback_at})
    emit_event(OPERATOR_ACTION, None, lead_id, {"action": "schedule_callback", "callback_at": req.callback_at})
    logger.info("schedule_callback lead_id={} at={}", lead_id, req.callback_at)
    return {"success": True, "lead_id": lead_id, "callback_at": req.callback_at}


@router.patch("/workflow/leads/{lead_id}/notes")
async def update_notes(lead_id: str, req: NotesRequest):
    from backend.lib.db import update_operator_notes
    from backend.voice.events import emit_event, OPERATOR_ACTION

    update_operator_notes(lead_id, req.notes)
    emit_event(OPERATOR_ACTION, None, lead_id, {"action": "notes_updated"})
    logger.info("operator_notes lead_id={}", lead_id)
    return {"success": True, "lead_id": lead_id}


@router.post("/workflow/leads/{lead_id}/pause")
async def pause_workflow(lead_id: str):
    from backend.workflows.engine import transition_state
    from backend.lib.db import pause_lead_drip
    from backend.voice.events import emit_event, OPERATOR_ACTION, WORKFLOW_UPDATED

    transition_state(lead_id, "dead_lead", triggered_by="operator_pause")
    pause_lead_drip(lead_id)
    emit_event(OPERATOR_ACTION, None, lead_id, {"action": "pause_workflow"})
    emit_event(WORKFLOW_UPDATED, None, lead_id, {"state": "dead_lead", "reason": "operator_pause"})
    logger.info("pause_workflow lead_id={}", lead_id)
    return {"success": True, "lead_id": lead_id, "state": "dead_lead"}


# ── Followup action endpoints ─────────────────────────────────────

@router.post("/workflow/leads/{lead_id}/walkthrough")
async def update_walkthrough(lead_id: str, req: WalkthroughRequest):
    from backend.lib.db import update_walkthrough_state, _get_client
    from backend.voice.events import emit_event, WORKFLOW_UPDATED

    valid_states = ("none", "scheduled", "completed", "missed", "cancelled")
    if req.state not in valid_states:
        raise HTTPException(status_code=400, detail=f"state must be one of {valid_states}")

    client = _get_client()
    if not client.table("leads").select("id").eq("id", lead_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_walkthrough_state(lead_id, req.state, req.notes, req.completed_at)
    emit_event(WORKFLOW_UPDATED, None, lead_id, {
        "action": "walkthrough_updated",
        "walkthrough_state": req.state,
    })
    logger.info("walkthrough_update lead_id={} state={}", lead_id, req.state)
    return {"success": True, "lead_id": lead_id, "walkthrough_state": req.state}


@router.post("/workflow/followups/{followup_id}/complete")
async def complete_followup(followup_id: str):
    from backend.lib.db import complete_followup as _complete
    _complete(followup_id)
    return {"success": True, "followup_id": followup_id, "state": "completed"}


@router.post("/workflow/followups/{followup_id}/cancel")
async def cancel_followup(followup_id: str):
    from backend.lib.db import cancel_followup as _cancel
    _cancel(followup_id)
    return {"success": True, "followup_id": followup_id, "state": "cancelled"}
