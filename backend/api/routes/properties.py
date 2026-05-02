from fastapi import APIRouter, Query
from loguru import logger
from backend.lib.db import (
    get_properties_by_score,
    get_new_properties_since,
    get_property_by_id,
    upsert_property,
)

router = APIRouter()


@router.get("/properties")
async def list_properties(
    min_score: int = Query(default=0),
    hours: int = Query(default=0),
    status: str = Query(default=""),
    limit: int = Query(default=100),
):
    if hours > 0:
        properties = get_new_properties_since(hours)
    else:
        properties = get_properties_by_score(min_score)

    if status:
        properties = [p for p in properties if p.get("status") == status]

    properties = properties[:limit]
    logger.info("list_properties count={}", len(properties))
    return {"properties": properties, "count": len(properties)}


@router.get("/properties/{property_id}")
async def get_property(property_id: str):
    prop = get_property_by_id(property_id)
    if not prop:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.patch("/properties/{property_id}/status")
async def update_property_status(property_id: str, status: str):
    from backend.lib.db import _get_client
    client = _get_client()
    client.table("properties").update({"status": status}).eq("id", property_id).execute()
    logger.info("property status updated id={} status={}", property_id, status)
    return {"success": True, "property_id": property_id, "status": status}


@router.post("/properties/{property_id}/comps")
async def trigger_comps(property_id: str):
    prop = get_property_by_id(property_id)
    if not prop:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Property not found")

    from backend.comps.redfin import get_comps
    from backend.comps.calculator import calculate_arv
    from backend.lib.db import update_property_arv

    comps = get_comps(
        address=prop.get("address", ""),
        city=prop.get("city", ""),
        state=prop.get("state", "CA"),
        beds=prop.get("beds"),
        baths=prop.get("baths"),
        sqft=prop.get("sqft"),
    )

    result = calculate_arv(comps, prop.get("sqft"))

    if result["arv"]:
        update_property_arv(
            property_id,
            result["arv"],
            result["mao"],
            result["confidence"],
        )

    logger.info("comps triggered property_id={} arv={}", property_id, result.get("arv"))
    return {"property_id": property_id, **result, "comp_count": len(comps)}
