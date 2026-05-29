from fastapi import APIRouter, Query, HTTPException
from loguru import logger

router = APIRouter()

_CALL_INTEL_FIELDS = (
    "id, lead_id, signalwire_call_id, direction, call_disposition, call_summary, "
    "seller_name, seller_motivation, motivation_confidence, timeline_urgency, "
    "asking_price, occupancy, property_condition, distress_indicators, objections, "
    "appointment_interest, next_step, followup_priority, lead_score, extraction_confidence"
)


@router.get("/calls")
async def list_calls(
    lead_id: str = Query(default=""),
    min_score: float = Query(default=0.0),
    limit: int = Query(default=50),
):
    from backend.lib.db import _get_client
    client = _get_client()

    query = client.table("calls").select("*")

    if lead_id:
        query = query.eq("lead_id", lead_id)

    if min_score > 0:
        query = query.gte("score_overall", min_score)

    response = query.order("created_at", desc=True).limit(limit).execute()
    calls = response.data
    logger.info("list_calls count={}", len(calls))
    return {"calls": calls, "count": len(calls)}


@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    from backend.lib.db import _get_client
    client = _get_client()
    response = (
        client.table("calls")
        .select("*")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Call not found")
    return response.data[0]


@router.post("/calls/{call_id}/grade")
async def grade_call_manually(call_id: str):
    from backend.lib.db import _get_client
    client = _get_client()
    response = (
        client.table("calls")
        .select("transcript, lead_id, signalwire_call_id")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Call not found")

    call = response.data[0]
    transcript = call.get("transcript", "")
    if not transcript:
        raise HTTPException(status_code=400, detail="Call has no transcript to grade")

    from backend.qa.grader import grade_call
    scores = grade_call(
        transcript=transcript,
        lead_id=call.get("lead_id", ""),
        call_sid=call.get("signalwire_call_id", call_id),
    )
    return {"call_id": call_id, "scores": scores}


@router.get("/calls/{call_id}/transcript")
async def get_call_transcript(call_id: str):
    from backend.lib.db import get_transcript_chunks, reconstruct_transcript_from_chunks, _get_client
    client = _get_client()

    call_resp = (
        client.table("calls")
        .select("id, lead_id, transcript")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not call_resp.data:
        raise HTTPException(status_code=404, detail="Call not found")

    call = call_resp.data[0]
    chunks = get_transcript_chunks(call_id)

    if not chunks and call.get("transcript"):
        flat = call["transcript"]
    elif chunks:
        flat = reconstruct_transcript_from_chunks(call_id)
    else:
        flat = ""

    logger.info("get_call_transcript call_id={} chunks={}", call_id, len(chunks))
    return {
        "call_id": call_id,
        "chunks": chunks,
        "flat_transcript": flat,
        "chunk_count": len(chunks),
    }


@router.get("/calls/{call_id}/intel")
async def get_call_intel(call_id: str):
    from backend.lib.db import _get_client
    client = _get_client()

    response = (
        client.table("calls")
        .select(_CALL_INTEL_FIELDS)
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Call not found")

    call = response.data[0]
    events_resp = (
        client.table("call_events")
        .select("event_type, payload, created_at")
        .eq("call_id", call_id)
        .order("created_at")
        .execute()
    )
    logger.info("get_call_intel call_id={}", call_id)
    return {
        "call_id": call_id,
        "intel": call,
        "events": events_resp.data,
    }


@router.post("/calls/{call_id}/intel/rerun")
async def rerun_call_intel(call_id: str):
    from backend.lib.db import _get_client, reconstruct_transcript_from_chunks
    client = _get_client()

    call_resp = (
        client.table("calls")
        .select("id, transcript, lead_id, signalwire_call_id")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )
    if not call_resp.data:
        raise HTTPException(status_code=404, detail="Call not found")

    call = call_resp.data[0]
    transcript = call.get("transcript") or reconstruct_transcript_from_chunks(call_id)
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript available for this call")

    lead_id = call.get("lead_id", "")
    call_sid = call.get("signalwire_call_id", call_id)

    from backend.qa.transcript_intel import analyze_transcript
    import asyncio
    intel = await asyncio.to_thread(analyze_transcript, transcript, lead_id, call_sid, call_id)
    logger.info("rerun_call_intel call_id={}", call_id)
    return {"call_id": call_id, "intel": intel}


@router.get("/calls/performance/summary")
async def get_performance_summary(days: int = Query(default=7)):
    from backend.qa.metrics import get_agent_performance_summary
    summary = get_agent_performance_summary(days=days)
    return summary


@router.get("/calls/performance/trend")
async def get_performance_trend(weeks: int = Query(default=4)):
    from backend.qa.metrics import get_qa_trend
    trend = get_qa_trend(weeks=weeks)
    return {"trend": trend}


@router.post("/campaigns/pause")
async def pause_campaign(campaign_id: str = "default"):
    try:
        from backend.lib.db import _get_client
        db = _get_client()
        db.table("campaigns").update({"state": "paused"}).eq("id", campaign_id).execute()
        logger.info("campaign_paused id={}", campaign_id)
        return {"success": True, "state": "paused"}
    except Exception as e:
        logger.error("pause_campaign failed error={}", str(e))
        return {"success": False, "error": str(e)}


@router.post("/campaigns/resume")
async def resume_campaign(campaign_id: str = "default"):
    try:
        from backend.lib.db import _get_client
        db = _get_client()
        db.table("campaigns").update({"state": "running"}).eq("id", campaign_id).execute()
        logger.info("campaign_resumed id={}", campaign_id)
        return {"success": True, "state": "running"}
    except Exception as e:
        logger.error("resume_campaign failed error={}", str(e))
        return {"success": False, "error": str(e)}


@router.post("/campaigns/redial/{campaign_id}")
async def redial_campaign(campaign_id: str):
    try:
        from backend.lib.db import _get_client
        db = _get_client()
        result = db.table("calls").select("lead_id").eq(
            "campaign_id", campaign_id
        ).in_("call_disposition", ["no_answer", "busy"]).execute()
        lead_ids = [r["lead_id"] for r in (result.data or []) if r.get("lead_id")]
        logger.info("campaign_redial campaign_id={} leads={}", campaign_id, len(lead_ids))
        return {"success": True, "leads_queued": len(lead_ids), "lead_ids": lead_ids}
    except Exception as e:
        logger.error("redial_campaign failed error={}", str(e))
        return {"success": False, "error": str(e)}


@router.get("/campaigns/status")
async def get_campaign_status():
    try:
        from backend.lib.db import _get_client
        db = _get_client()
        result = db.table("campaigns").select("*").order("created_at", desc=True).limit(5).execute()
        return {"campaigns": result.data or []}
    except Exception as e:
        return {"campaigns": [], "error": str(e)}
