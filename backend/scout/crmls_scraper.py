import os
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

CRMLS_API_BASE = "https://api.crmls.org/reso/odata"

SAN_JOAQUIN_CITIES = [
    "Stockton", "Lodi", "Manteca", "Tracy", "Turlock",
    "Modesto", "Ripon", "Escalon", "Lathrop", "Holt",
]

_SELECT_FIELDS = ",".join([
    "ListingId",
    "UnparsedAddress",
    "City",
    "StateOrProvince",
    "ListPrice",
    "BedroomsTotal",
    "BathroomsTotalInteger",
    "LivingArea",
    "YearBuilt",
    "DaysOnMarket",
    "PriceChangeTimestamp",
    "OffMarketDate",
    "MlsStatus",
])


def _dom_bonus(days_on_market: int) -> int:
    if days_on_market > 180:
        return 25
    if days_on_market > 90:
        return 15
    return 0


def _build_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _item_to_prop(item: dict, distress_type: str) -> dict:
    list_price = item.get("ListPrice") or 0
    list_price_cents = round(list_price * 100)
    days_on_market = item.get("DaysOnMarket") or 0

    return {
        "address": item.get("UnparsedAddress", ""),
        "city": item.get("City", ""),
        "state": item.get("StateOrProvince", "CA"),
        "county": "San Joaquin",
        "estimated_value": list_price_cents,
        "beds": item.get("BedroomsTotal"),
        "baths": item.get("BathroomsTotalInteger"),
        "sqft": item.get("LivingArea"),
        "year_built": item.get("YearBuilt"),
        "distress_type": distress_type,
        "dom_bonus": _dom_bonus(days_on_market),
        "status": "new",
    }


def fetch_expired_listings(days_back: int = 7) -> list[dict]:
    api_key = os.environ.get("CRMLS_API_KEY")
    member_id = os.environ.get("CRMLS_MEMBER_ID")
    if not api_key or not member_id:
        logger.warning("crmls_scraper: CRMLS_API_KEY or CRMLS_MEMBER_ID not set, skipping")
        return []

    leads = []
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$filter": f"MlsStatus eq 'Expired' and OffMarketDate ge {cutoff}",
        "$select": _SELECT_FIELDS,
        "$top": "50",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{CRMLS_API_BASE}/Property",
                params=params,
                headers=_build_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                leads.append(_item_to_prop(item, "expired_listing"))
    except Exception as e:
        logger.error("crmls_scraper fetch_expired failed error={}", str(e))

    logger.info("crmls_scraper expired listings count={}", len(leads))
    return leads


def fetch_price_reduced_listings(days_back: int = 7) -> list[dict]:
    api_key = os.environ.get("CRMLS_API_KEY")
    member_id = os.environ.get("CRMLS_MEMBER_ID")
    if not api_key or not member_id:
        logger.warning("crmls_scraper: CRMLS_API_KEY or CRMLS_MEMBER_ID not set, skipping")
        return []

    leads = []
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$filter": (
            f"MlsStatus eq 'Active' "
            f"and PriceChangeTimestamp ge {cutoff}"
        ),
        "$select": _SELECT_FIELDS,
        "$top": "50",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{CRMLS_API_BASE}/Property",
                params=params,
                headers=_build_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                leads.append(_item_to_prop(item, "price_reduction"))
    except Exception as e:
        logger.error("crmls_scraper fetch_price_reduced failed error={}", str(e))

    logger.info("crmls_scraper price_reduced listings count={}", len(leads))
    return leads


def fetch_withdrawn_listings(days_back: int = 7) -> list[dict]:
    api_key = os.environ.get("CRMLS_API_KEY")
    member_id = os.environ.get("CRMLS_MEMBER_ID")
    if not api_key or not member_id:
        logger.warning("crmls_scraper: CRMLS_API_KEY or CRMLS_MEMBER_ID not set, skipping")
        return []

    leads = []
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$filter": (
            f"MlsStatus eq 'Withdrawn' "
            f"and OffMarketDate ge {cutoff}"
        ),
        "$select": _SELECT_FIELDS,
        "$top": "50",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{CRMLS_API_BASE}/Property",
                params=params,
                headers=_build_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                leads.append(_item_to_prop(item, "withdrawn_listing"))
    except Exception as e:
        logger.error("crmls_scraper fetch_withdrawn failed error={}", str(e))

    logger.info("crmls_scraper withdrawn listings count={}", len(leads))
    return leads


def run_crmls_scraper() -> int:
    expired = fetch_expired_listings()
    reduced = fetch_price_reduced_listings()
    withdrawn = fetch_withdrawn_listings()
    total = len(expired) + len(reduced) + len(withdrawn)
    logger.info(
        "crmls_scraper run complete expired={} reduced={} withdrawn={} total={}",
        len(expired),
        len(reduced),
        len(withdrawn),
        total,
    )
    return total
