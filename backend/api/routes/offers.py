from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

OFFER_STATUSES = ("draft", "sent", "countered", "accepted", "rejected", "expired")


class OfferCreateRequest(BaseModel):
    lead_id: str
    arv_used: Optional[int] = None          # cents; if None, pulls from property
    repair_estimate: int = 2500000          # cents, default $25k
    offer_amount: Optional[int] = None      # cents; if None, uses mao_calculated
    property_id: Optional[str] = None
    notes: Optional[str] = None
    created_by: str = "operator"


class OfferStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@router.post("/offers")
async def create_offer_endpoint(req: OfferCreateRequest):
    from backend.lib.db import create_offer, _get_client, get_offer_by_id

    arv_used = req.arv_used

    # If no ARV provided, pull from property
    if arv_used is None and req.property_id:
        client = _get_client()
        prop_resp = (
            client.table("properties")
            .select("estimated_arv")
            .eq("id", req.property_id)
            .limit(1)
            .execute()
        )
        if prop_resp.data:
            arv_used = prop_resp.data[0].get("estimated_arv")

    # Try property from lead if still None
    if arv_used is None:
        client = _get_client()
        lead_resp = (
            client.table("leads")
            .select("property_id, properties(estimated_arv)")
            .eq("id", req.lead_id)
            .limit(1)
            .execute()
        )
        if lead_resp.data:
            prop = lead_resp.data[0].get("properties") or {}
            arv_used = prop.get("estimated_arv")
            if not req.property_id:
                req.property_id = lead_resp.data[0].get("property_id")

    offer_id = create_offer(
        lead_id=req.lead_id,
        arv_used=arv_used,
        repair_estimate=req.repair_estimate,
        offer_amount=req.offer_amount,
        property_id=req.property_id,
        notes=req.notes,
        created_by=req.created_by,
    )
    if not offer_id:
        raise HTTPException(status_code=500, detail="Failed to create offer")

    offer = get_offer_by_id(offer_id)
    logger.info("create_offer lead_id={} offer_id={}", req.lead_id, offer_id)
    return {"success": True, "offer": offer}


@router.get("/offers/{offer_id}")
async def get_offer_endpoint(offer_id: str):
    from backend.lib.db import get_offer_by_id
    offer = get_offer_by_id(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


@router.patch("/offers/{offer_id}/status")
async def update_offer_status_endpoint(offer_id: str, req: OfferStatusRequest):
    from backend.lib.db import update_offer_status, get_offer_by_id

    if req.status not in OFFER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{req.status}'. Valid: {OFFER_STATUSES}",
        )

    offer = get_offer_by_id(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    update_offer_status(offer_id, req.status, req.notes)
    logger.info("update_offer_status offer_id={} status={}", offer_id, req.status)
    return {"success": True, "offer_id": offer_id, "status": req.status}


@router.get("/leads/{lead_id}/offers")
async def get_lead_offers_endpoint(lead_id: str):
    from backend.lib.db import get_offers_for_lead, _get_client
    client = _get_client()
    if not client.table("leads").select("id").eq("id", lead_id).limit(1).execute().data:
        raise HTTPException(status_code=404, detail="Lead not found")
    offers = get_offers_for_lead(lead_id)
    return {"lead_id": lead_id, "offers": offers, "count": len(offers)}
