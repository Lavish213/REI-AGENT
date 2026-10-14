import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

CRMLS_API_BASE = "https://api.crmls.org/reso/odata"

_SELECT_FIELDS = ",".join([
    "ListingId",
    "ParcelNumber",
    "UnparsedAddress",
    "City",
    "StateOrProvince",
    "ListPrice",
    "PreviousListPrice",
    "CountyOrParish",
    "PropertyType",
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
    county = item.get("CountyOrParish")
    if not isinstance(county, str) or county.strip().lower() not in {"san joaquin", "san joaquin county"} or item.get("StateOrProvince") != "CA" or item.get("PropertyType") != "Residential":
        return {}
    try:
        price = Decimal(str(item.get("ListPrice")))
        if not price.is_finite() or price <= 0 or price > 10**12 or price * 100 != (price * 100).to_integral_value():
            return {}
        if distress_type == "price_reduction":
            prior = Decimal(str(item.get("PreviousListPrice")))
            if not prior.is_finite() or prior <= price:
                return {}
    except (InvalidOperation, ValueError, TypeError):
        return {}
    days_on_market = item.get("DaysOnMarket") or 0
    if type(days_on_market) is not int or not 0 <= days_on_market <= 10000:
        return {}
    apn = str(item.get("ParcelNumber") or "").strip().replace("-", "")
    if len(apn) != 8 or not apn.isascii() or not apn.isdigit() or apn == "00000000":
        apn = None

    return {
        "apn": apn,
        "_source_listing_id": str(item.get("ListingId") or ""),
        "last_list_price": int(price * 100),
        "distress_score": min(100, 50 + _dom_bonus(days_on_market)),
        "deal_viable": False,
        "address": item.get("UnparsedAddress", ""),
        "city": item.get("City", ""),
        "state": item.get("StateOrProvince", "CA"),
        "county": "San Joaquin",
        "estimated_value": None,
        "beds": item.get("BedroomsTotal"),
        "baths": item.get("BathroomsTotalInteger"),
        "sqft": item.get("LivingArea"),
        "year_built": item.get("YearBuilt"),
        "distress_type": distress_type,
        "dom_bonus": _dom_bonus(days_on_market),
        "days_on_market": days_on_market,
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
                prop = _item_to_prop(item, "expired_listing")
                if prop:
                    leads.append(prop)
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
                prop = _item_to_prop(item, "price_reduction")
                if prop:
                    leads.append(prop)
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
                prop = _item_to_prop(item, "withdrawn_listing")
                if prop:
                    leads.append(prop)
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
    from backend.lib.db import persist_mls_candidate
    saved = 0
    for prop in expired + reduced + withdrawn:
        try:
            if persist_mls_candidate(prop):
                saved += 1
        except Exception as error:
            logger.warning("mls_candidate_persistence_failed type={}", type(error).__name__)
    logger.info("crmls_candidates_saved={} withheld={}", saved, total - saved)
    return saved
