from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend.lib.db import add_walkthrough_availability, list_walkthrough_availability


router = APIRouter()


class AvailabilitySlot(BaseModel):
    starts_at: datetime
    ends_at: datetime


@router.get("/appointments/availability")
async def get_availability():
    return {"slots": await run_in_threadpool(list_walkthrough_availability)}


@router.post("/appointments/availability")
async def set_availability(slot: AvailabilitySlot):
    if slot.starts_at.tzinfo is None or slot.ends_at.tzinfo is None:
        raise HTTPException(400, "Include an explicit UTC offset")
    duration = slot.ends_at - slot.starts_at
    if slot.starts_at <= datetime.now(timezone.utc) or not timedelta(minutes=15) <= duration <= timedelta(hours=3):
        raise HTTPException(400, "Provide a future slot lasting 15 minutes to 3 hours")
    await run_in_threadpool(add_walkthrough_availability, slot.starts_at.isoformat(), slot.ends_at.isoformat())
    return {"saved": True}


@router.post("/operations/callback")
async def source_callback_command(body: dict):
    from backend.lib.db import apply_source_callback
    try:
        return await run_in_threadpool(apply_source_callback, body)
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(409, "Source command could not be applied; refresh and review") from error


@router.get("/operations/candidates")
async def source_candidates(page: int = 1):
    from backend.lib.db import list_source_candidates
    try:
        return {'items': await run_in_threadpool(list_source_candidates, page), 'page': page}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/operations/candidates/{identity}/review")
async def source_candidate_review(identity: str, body: dict):
    from backend.lib.db import review_source_candidate
    try:
        return await run_in_threadpool(review_source_candidate, identity, body['actor_id'], body['decision'], body['reason'], body['fingerprint'], body.get('lead_id'))
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(422, 'Explicit candidate review required') from error


@router.get('/operations/price-reviews')
async def price_reviews(page: int = 1):
    from backend.lib.db import list_source_price_reviews
    try:
        return await run_in_threadpool(list_source_price_reviews, page)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post('/operations/price-reviews/{identity}/resolve')
async def resolve_price_review(identity: str, body: dict):
    from backend.lib.db import resolve_source_price_review
    try:
        return await run_in_threadpool(resolve_source_price_review, identity, body)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(409, 'Decision not confirmed; refresh source review') from error


@router.post('/operations/command')
async def source_operation(body: dict):
    from backend.lib.db import apply_source_operation
    try:
        return await run_in_threadpool(apply_source_operation, body)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(409, 'Operation not applied; refresh source version and review') from error


@router.get('/operations/email-holds')
async def email_holds(page: int = 1):
    from backend.lib.db import list_email_reply_holds
    try:
        return await run_in_threadpool(list_email_reply_holds, page)
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error


@router.post('/operations/email-holds/{lead_id}/resume', status_code=202)
async def resume_email(lead_id: str, body: dict):
    from backend.lib.db import review_email_resumption
    try:
        return await run_in_threadpool(review_email_resumption, lead_id, body)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(409, 'Resumption needs a current operator review; STOP remains blocked') from error
