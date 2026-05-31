from __future__ import annotations
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
from loguru import logger

router = APIRouter()


@router.post("/intel/packets/{lead_id}")
async def bob_write_packet(lead_id: str, payload: dict):
    from backend.lib.db import load_intel_packet, save_intel_packet, write_packet_event
    from backend.contracts.intel_packet import migrate_packet, PACKET_SCHEMA_VERSION
    payload["lead_id"] = lead_id
    payload["schema_version"] = PACKET_SCHEMA_VERSION
    if "packet_state" not in payload:
        payload["packet_state"] = "bob_enriched"
    existing = await run_in_threadpool(load_intel_packet, lead_id)
    before = existing or {}
    await run_in_threadpool(save_intel_packet, payload)
    changed = [k for k in payload if payload.get(k) != before.get(k)]
    await run_in_threadpool(
        write_packet_event, lead_id, "", "bob_write",
        before, payload, changed, "bob",
    )
    logger.info("bob_write_packet lead_id={} changed={}", lead_id, changed)
    return {"success": True, "lead_id": lead_id, "changed_fields": changed}


@router.get("/intel/packets/{lead_id}")
async def get_packet(lead_id: str):
    from backend.lib.db import load_intel_packet
    from backend.contracts.intel_packet import migrate_packet
    packet = await run_in_threadpool(load_intel_packet, lead_id)
    if not packet:
        raise HTTPException(status_code=404, detail="No intel packet found")
    return migrate_packet(packet)


@router.get("/intel/packets/{lead_id}/signals")
async def get_signals(lead_id: str, limit: int = 20):
    from backend.lib.db import _get_client
    client = _get_client()
    resp = (
        client.table("bob_feedback_events")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"events": resp.data or []}


@router.get("/intel/packets/{lead_id}/events")
async def get_packet_events(lead_id: str, limit: int = 50):
    from backend.lib.db import _get_client
    client = _get_client()
    resp = (
        client.table("packet_events")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"events": resp.data or []}


@router.post("/intel/approvals/{approval_id}/resolve")
async def resolve_approval(approval_id: str, body: dict):
    from backend.lib.db import resolve_approval_request
    status = body.get("status", "approved")
    approved_by = body.get("approved_by", "dashboard")
    answer = body.get("answer", "")
    await run_in_threadpool(resolve_approval_request, approval_id, approved_by, status, answer)
    return {"success": True, "approval_id": approval_id, "status": status}


@router.get("/intel/approvals/pending")
async def get_pending_approvals(limit: int = 20):
    from datetime import datetime, timezone
    from backend.lib.db import _get_client
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        client.table("approval_requests")
        .select("*")
        .eq("status", "pending")
        .gt("expires_at", now)
        .order("priority", desc=False)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return {"approvals": resp.data or []}
