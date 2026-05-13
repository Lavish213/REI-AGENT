from fastapi import APIRouter, Query
from loguru import logger

router = APIRouter()


@router.post("/evals/run")
async def run_evals(count: int = Query(default=5)):
    from backend.voice.simulator import run_batch_simulations
    results = await run_batch_simulations(count=count)
    passed = sum(1 for r in results if r.get("overall_score", 0) >= 7.0)
    booked = sum(1 for r in results if r.get("appointment_booked"))
    avg_score = sum(r.get("overall_score", 0) for r in results) / len(results) if results else 0

    logger.info("evals run count={} passed={} booked={} avg={}", count, passed, booked, avg_score)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "appointments_booked": booked,
        "avg_score": round(avg_score, 2),
        "results": results,
    }


@router.get("/evals/history")
async def get_eval_history(limit: int = Query(default=10)):
    from backend.lib.db import _get_client
    client = _get_client()
    response = (
        client.table("eval_runs")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"runs": response.data, "count": len(response.data)}
