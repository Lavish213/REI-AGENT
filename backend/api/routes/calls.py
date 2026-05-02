from fastapi import APIRouter, Query, HTTPException
from loguru import logger

router = APIRouter()


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
