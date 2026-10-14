from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter()
OFFER_STATUSES = ("draft", "sent", "countered", "accepted", "rejected", "expired")
Cents = Annotated[int, Field(strict=True, ge=0, le=10**14)]


class OfferCreateRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=255)
    arv_used: Optional[Annotated[int, Field(strict=True, gt=0, le=10**14)]] = None
    repair_estimate: Cents = 2500000
    offer_amount: Optional[Cents] = None
    property_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=10000)
    created_by: str = Field(default="operator", max_length=255)


class OfferStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=10000)


async def bound_subject(lead_id, property_id=None):
    from backend.lib.db import offer_subject
    try:
        return await run_in_threadpool(offer_subject, lead_id, property_id)
    except LookupError as error:
        raise HTTPException(404, "Lead not found") from error
    except ValueError as error:
        raise HTTPException(409, "Offer property or tenant binding mismatch") from error


@router.post("/offers")
async def create_offer_endpoint(req: OfferCreateRequest, request: Request):
    from backend.lib.db import create_offer, get_offer_by_id
    prop = await bound_subject(req.lead_id, req.property_id)
    arv = req.arv_used if req.arv_used is not None else prop.get("estimated_arv")
    if arv is not None and (type(arv) is not int or not 0 < arv <= 10**14):
        raise HTTPException(422, "Property valuation must be positive integer cents")
    operator = getattr(request.state, "operator", None)
    actor = str(operator.id) if operator is not None else "operator"
    offer_id = await run_in_threadpool(create_offer, lead_id=req.lead_id, arv_used=arv, repair_estimate=req.repair_estimate, offer_amount=req.offer_amount, property_id=prop["id"], notes=req.notes, created_by=actor)
    if not offer_id:
        raise HTTPException(500, "Failed to create offer")
    offer = await run_in_threadpool(get_offer_by_id, offer_id)
    if not offer or offer.get("id") != offer_id or offer.get("lead_id") != req.lead_id or offer.get("property_id") != prop["id"]:
        raise HTTPException(503, "Offer readback was not confirmed")
    logger.info("create_offer lead_id={} offer_id={}", req.lead_id, offer_id)
    return {"success": True, "offer": offer}


@router.get("/offers/{offer_id}")
async def get_offer_endpoint(offer_id: str):
    from backend.lib.db import get_offer_by_id
    offer = await run_in_threadpool(get_offer_by_id, offer_id)
    if not offer:
        raise HTTPException(404, "Offer not found")
    await bound_subject(offer.get("lead_id"), offer.get("property_id"))
    return offer


@router.patch("/offers/{offer_id}/status")
async def update_offer_status_endpoint(offer_id: str, req: OfferStatusRequest):
    from backend.lib.db import update_offer_status, get_offer_by_id
    if req.status not in OFFER_STATUSES:
        raise HTTPException(400, "Invalid offer status")
    offer = await run_in_threadpool(get_offer_by_id, offer_id)
    if not offer:
        raise HTTPException(404, "Offer not found")
    await bound_subject(offer.get("lead_id"), offer.get("property_id"))
    try:
        await run_in_threadpool(update_offer_status, offer_id, req.status, req.notes)
    except RuntimeError as error:
        raise HTTPException(503, "Offer status persistence was not confirmed") from error
    logger.info("update_offer_status offer_id={} status={}", offer_id, req.status)
    return {"success": True, "offer_id": offer_id, "status": req.status}


@router.get("/leads/{lead_id}/offers")
async def get_lead_offers_endpoint(lead_id: str):
    from backend.lib.db import get_offers_for_lead
    await bound_subject(lead_id)
    offers = await run_in_threadpool(get_offers_for_lead, lead_id)
    return {"lead_id": lead_id, "offers": offers, "count": len(offers)}
