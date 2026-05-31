import io

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.concurrency import run_in_threadpool
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


@router.post("/properties/upload")
async def upload_properties_csv(
    file: UploadFile = File(...),
    min_score: int = Query(default=0),
    create_leads: bool = Query(default=True),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        csv_text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = contents.decode("latin-1")

    def _process(csv_text: str, min_score: int, create_leads: bool) -> dict:
        from backend.scout.parser import parse_csv
        from backend.scout.scorer import calculate_distress_score
        from backend.lib.db import insert_lead, get_lead_by_property

        properties = parse_csv(io.StringIO(csv_text))
        logger.info("csv_upload parsed={}", len(properties))

        upserted = 0
        scored = 0
        leads_created = 0
        skipped_score = 0
        errors = 0

        for prop in properties:
            try:
                score_result = calculate_distress_score(prop)
                if score_result.get("disqualified"):
                    errors += 1
                    continue

                prop["distress_score"] = score_result["score"]
                prop["distress_type"] = score_result.get("distress_type", prop.get("distress_type", "unknown"))

                upsert_property(prop)
                upserted += 1

                if score_result["score"] < min_score:
                    skipped_score += 1
                    continue

                scored += 1

                if create_leads and prop.get("id"):
                    existing = get_lead_by_property(prop["id"])
                    if not existing:
                        csv_phone = prop.pop("_owner_phone", None)
                        csv_phone_2 = prop.pop("_owner_phone_2", None)
                        csv_email = prop.pop("_owner_email", None)
                        lead_id = insert_lead(prop["id"])
                        leads_created += 1
                        if csv_phone or csv_email:
                            try:
                                from backend.lib.db import _get_client
                                from datetime import datetime, timezone
                                lead_upd = {"updated_at": datetime.now(timezone.utc).isoformat()}
                                if csv_phone:
                                    lead_upd["owner_phone"] = csv_phone
                                    lead_upd["callable"] = True
                                if csv_email:
                                    lead_upd["owner_email"] = csv_email
                                _get_client().table("leads").update(lead_upd).eq("id", lead_id).execute()
                                logger.info("csv_phone_stored lead_id={}", lead_id)
                            except Exception as ph_err:
                                logger.warning("csv_phone_store failed error={}", str(ph_err))
                    else:
                        prop.pop("_owner_phone", None)
                        prop.pop("_owner_phone_2", None)
                        prop.pop("_owner_email", None)

            except Exception as e:
                logger.warning("csv_upload row_error error={}", str(e))
                errors += 1

        return {
            "parsed": len(properties),
            "upserted": upserted,
            "scored": scored,
            "leads_created": leads_created,
            "skipped_score": skipped_score,
            "errors": errors,
        }

    result = await run_in_threadpool(_process, csv_text, min_score, create_leads)
    logger.info("csv_upload complete result={}", result)
    return {"success": True, **result}
