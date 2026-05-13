from fastapi import APIRouter, Query
from loguru import logger  # noqa: F401 — used in revenue-pipeline

router = APIRouter()


@router.get("/analytics/pipeline")
async def get_pipeline():
    from backend.lib.db import _get_client
    client = _get_client()

    stages = [
        "new", "contacted", "offer_made",
        "walkthrough_booked", "under_contract", "closed", "dead"
    ]

    pipeline = {}
    for stage in stages:
        response = (
            client.table("leads")
            .select("id", count="exact")
            .eq("stage", stage)
            .execute()
        )
        pipeline[stage] = response.count or 0

    return {"pipeline": pipeline}


@router.get("/analytics/leads-by-week")
async def get_leads_by_week(weeks: int = Query(default=8)):
    from backend.lib.db import _get_client
    from datetime import datetime, timezone, timedelta
    client = _get_client()

    result = []
    for i in range(weeks):
        week_end = datetime.now(timezone.utc) - timedelta(weeks=i)
        week_start = week_end - timedelta(weeks=1)

        response = (
            client.table("properties")
            .select("id", count="exact")
            .gte("created_at", week_start.isoformat())
            .lte("created_at", week_end.isoformat())
            .execute()
        )
        result.append({
            "week": f"Week -{i}",
            "week_start": week_start.date().isoformat(),
            "count": response.count or 0,
        })

    result.reverse()
    return {"weeks": result}


@router.get("/analytics/score-distribution")
async def get_score_distribution():
    from backend.lib.db import _get_client
    client = _get_client()

    bands = [
        ("90-100", 90, 100),
        ("75-89", 75, 89),
        ("50-74", 50, 74),
        ("25-49", 25, 49),
        ("0-24", 0, 24),
    ]

    distribution = {}
    for label, low, high in bands:
        response = (
            client.table("properties")
            .select("id", count="exact")
            .gte("distress_score", low)
            .lte("distress_score", high)
            .execute()
        )
        distribution[label] = response.count or 0

    return {"distribution": distribution}


@router.get("/analytics/workflow")
async def get_workflow_analytics():
    """Comprehensive workflow + pipeline analytics for the operator dashboard."""
    from backend.lib.db import get_workflow_analytics
    data = get_workflow_analytics()
    return data


@router.get("/analytics/revenue-pipeline")
async def get_revenue_pipeline():
    from backend.lib.db import _get_client
    client = _get_client()

    active_stages = ["offer_made", "walkthrough_booked", "under_contract"]
    response = (
        client.table("leads")
        .select("stage, offer_amount, properties(estimated_arv, mao)")
        .in_("stage", active_stages)
        .execute()
    )

    total_potential = 0
    deals_by_stage = {}

    for lead in response.data:
        stage = lead.get("stage")
        prop = lead.get("properties") or {}
        mao = prop.get("mao", 0) or 0

        if stage not in deals_by_stage:
            deals_by_stage[stage] = {"count": 0, "potential_value": 0}

        deals_by_stage[stage]["count"] += 1
        deals_by_stage[stage]["potential_value"] += mao
        total_potential += mao

    return {
        "total_potential_cents": total_potential,
        "total_potential_dollars": total_potential / 100,
        "deals_by_stage": deals_by_stage,
    }
