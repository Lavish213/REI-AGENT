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
