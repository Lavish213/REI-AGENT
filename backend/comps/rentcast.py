import os

import httpx
from loguru import logger

from backend.lib import db

BASE_URL = "https://api.rentcast.io/v1"
HARD_CAP = 50
MAX_BATCH = 50
PROPERTY_TYPES = (
    ("condo", "Condo"),
    ("townhouse", "Townhouse"),
    ("manufactured", "Manufactured"),
    ("mobile", "Manufactured"),
    ("duplex", "Multi-Family"),
    ("triplex", "Multi-Family"),
    ("fourplex", "Multi-Family"),
    ("multi", "Multi-Family"),
    ("single", "Single Family"),
    ("sfr", "Single Family"),
    ("residence", "Single Family"),
)


class RentcastDisabled(Exception):
    pass


class BudgetExhausted(Exception):
    pass


class RentcastRejected(Exception):
    pass


def monthly_cap() -> int:
    try:
        configured = int(os.environ.get("RENTCAST_MONTHLY_CAP", str(HARD_CAP)))
    except ValueError:
        return 0
    return max(0, min(configured, HARD_CAP))


def enabled() -> bool:
    return os.environ.get("RENTCAST_ENABLED", "false").strip().lower() == "true" and bool(os.environ.get("RENTCAST_API_KEY", "").strip())


def request_params(prop: dict) -> dict:
    street = (prop.get("address") or "").strip()
    city = (prop.get("city") or "").strip()
    state = (prop.get("state") or "CA").strip()
    postal = (prop.get("zip") or "").strip()
    params = {"address": ", ".join(part for part in (street, city, f"{state} {postal}".strip()) if part), "compCount": 20, "maxRadius": 5, "daysOld": 270}
    kind = (prop.get("property_type") or prop.get("land_use") or "").lower()
    for needle, label in PROPERTY_TYPES:
        if needle in kind:
            params["propertyType"] = label
            break
    for source, target in (("beds", "bedrooms"), ("baths", "bathrooms"), ("sqft", "squareFootage")):
        value = prop.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            params[target] = value
    return params


def value_estimate(prop: dict, transport: httpx.BaseTransport | None = None) -> dict | None:
    if not enabled():
        raise RentcastDisabled("RentCast is disabled")
    call_id = db.reserve_rentcast_call(prop.get("id"), monthly_cap())
    if call_id is None:
        raise BudgetExhausted("RentCast monthly cap reached")
    try:
        with httpx.Client(transport=transport, timeout=20, follow_redirects=False) as client:
            response = client.get(BASE_URL + "/avm/value", params=request_params(prop), headers={"X-Api-Key": os.environ["RENTCAST_API_KEY"].strip(), "Accept": "application/json"})
    except httpx.HTTPError:
        db.finish_rentcast_call(call_id, None, "error")
        raise
    status = response.status_code
    db.finish_rentcast_call(call_id, status, "ok" if status == 200 else "no_data" if status == 404 else "error")
    if status == 404:
        return None
    if status in (401, 403, 429):
        raise RentcastRejected(f"RentCast refused the request status={status}")
    if status != 200:
        raise RuntimeError(f"RentCast request failed status={status}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("RentCast returned an invalid body")
    return data


def price_batch(limit: int, transport: httpx.BaseTransport | None = None) -> dict:
    if not enabled():
        raise RentcastDisabled("RentCast is disabled")
    size = max(1, min(int(limit), MAX_BATCH))
    result = {"requested": size, "priced": 0, "no_data": 0, "errors": 0, "comps_saved": 0, "stopped": None}
    for prop in db.rentcast_candidates(size):
        try:
            data = value_estimate(prop, transport)
        except BudgetExhausted:
            result["stopped"] = "budget_exhausted"
            break
        except RentcastRejected as error:
            result["errors"] += 1
            result["stopped"] = str(error)
            break
        except Exception as error:
            result["errors"] += 1
            logger.warning("rentcast_valuation_failed property_id={} type={}", prop.get("id"), type(error).__name__)
            continue
        if data is None:
            db.mark_rentcast_no_data(prop["id"])
            result["no_data"] += 1
            continue
        try:
            result["comps_saved"] += db.save_rentcast_valuation(prop["id"], data)
            result["priced"] += 1
        except Exception as error:
            result["errors"] += 1
            logger.warning("rentcast_save_failed property_id={} type={}", prop.get("id"), type(error).__name__)
    result["usage"] = db.rentcast_usage()
    return result
