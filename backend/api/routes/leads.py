from fastapi import APIRouter, Query, HTTPException
from loguru import logger
from backend.lib.db import (
    get_leads_for_followup,
    insert_lead,
    update_lead_stage,
    get_lead_by_property,
    get_property_by_id,
)

router = APIRouter()


@router.get("/leads")
async def list_leads(
    stage: str = Query(default=""),
    limit: int = Query(default=100),
):
    from backend.lib.db import _get_client
    client = _get_client()

    query = client.table("leads").select("*, properties(*)")

    if stage:
        query = query.eq("stage", stage)

    response = query.order("created_at", desc=True).limit(limit).execute()
    leads = response.data
    logger.info("list_leads stage={} count={}", stage or "all", len(leads))
    return {"leads": leads, "count": len(leads)}


@router.get("/leads/followup")
async def get_followup_leads():
    leads = get_leads_for_followup()
    return {"leads": leads, "count": len(leads)}


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    from backend.lib.db import _get_client
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return response.data[0]


@router.post("/leads")
async def create_lead(property_id: str):
    existing = get_lead_by_property(property_id)
    if existing:
        return {"lead_id": existing["id"], "created": False}
    lead_id = insert_lead(property_id)
    return {"lead_id": lead_id, "created": True}


@router.patch("/leads/{lead_id}/stage")
async def update_stage(lead_id: str, stage: str):
    valid_stages = [
        "new", "contacted", "offer_made",
        "walkthrough_booked", "under_contract", "closed", "dead"
    ]
    if stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {valid_stages}")
    update_lead_stage(lead_id, stage)
    logger.info("lead stage updated lead_id={} stage={}", lead_id, stage)
    return {"success": True, "lead_id": lead_id, "stage": stage}


@router.patch("/leads/{lead_id}/notes")
async def update_notes(lead_id: str, notes: str):
    from backend.lib.db import _get_client
    client = _get_client()
    client.table("leads").update({"notes": notes}).eq("id", lead_id).execute()
    return {"success": True, "lead_id": lead_id}


@router.post("/leads/{lead_id}/enrich")
async def enrich_lead_endpoint(lead_id: str):
    from backend.lib.db import _get_client
    from backend.lib.batchdata import enrich_lead

    client = _get_client()
    lead_resp = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not lead_resp.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead = lead_resp.data[0]
    prop = lead.get("properties") or {}

    if not prop:
        raise HTTPException(status_code=422, detail="Lead has no associated property")

    try:
        result = enrich_lead(lead, prop)
        logger.info("enrich endpoint success lead_id={}", lead_id)
        return {"success": True, "lead_id": lead_id, "result": result}
    except Exception as e:
        logger.error("enrich endpoint failed lead_id={} error={}", lead_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))
