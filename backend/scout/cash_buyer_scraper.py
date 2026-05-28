from __future__ import annotations

import os
from datetime import datetime, timezone
from loguru import logger

_MAX_PRICE_CENTS = 250_000 * 100
_LOOKBACK_DAYS = 180


def _is_cash_transaction(deed):
    deed_type = (deed.get("deed_type") or "").lower()
    mortgage_recorded = deed.get("mortgage_recorded", False)
    has_warranty = "warranty" in deed_type or "grant" in deed_type
    return has_warranty and not mortgage_recorded


def _is_residential(deed):
    prop_type = (deed.get("property_type") or "").lower()
    return any(t in prop_type for t in ("single family", "residential", "sfr", "house", ""))


def _is_in_price_range(deed):
    price = deed.get("sale_price") or deed.get("consideration_amount") or 0
    return 0 < int(price) <= _MAX_PRICE_CENTS


def _is_recent(deed):
    date_str = deed.get("recorded_date") or deed.get("sale_date") or ""
    if not date_str:
        return False
    try:
        recorded = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - recorded).days <= _LOOKBACK_DAYS
    except Exception:
        return False


def scrape_cash_buyers(county="San Joaquin", zip_codes=None):
    logger.info("cash_buyer_scraper starting county={}", county)
    buyers = []

    try:
        from backend.lib.db import get_recent_deed_transfers
        deeds = get_recent_deed_transfers(county=county, days=_LOOKBACK_DAYS)
    except Exception as e:
        logger.warning("cash_buyer_scraper deed fetch failed error={}", str(e))
        deeds = []

    for deed in deeds:
        if not all([_is_cash_transaction(deed), _is_residential(deed), _is_in_price_range(deed), _is_recent(deed)]):
            continue

        buyer_name = deed.get("grantee_name") or deed.get("buyer_name") or ""
        address = deed.get("property_address") or ""
        zip_code = deed.get("zip") or deed.get("zip_code") or ""
        sale_price = deed.get("sale_price") or deed.get("consideration_amount") or 0

        if zip_codes and zip_code not in zip_codes:
            continue

        buyers.append({
            "name": buyer_name,
            "purchase_address": address,
            "purchase_price_cents": int(sale_price),
            "zip_code": zip_code,
            "county": county,
            "last_active_date": deed.get("recorded_date") or deed.get("sale_date"),
            "source": "county_deed_records",
        })

    logger.info("cash_buyer_scraper found {} raw buyers", len(buyers))
    return buyers


def enrich_and_save_buyers(buyers):
    saved = 0
    for buyer in buyers:
        try:
            phone = _skip_trace_buyer(buyer)
            if phone:
                buyer["phone"] = phone
            from backend.lib.db import upsert_cash_buyer
            upsert_cash_buyer(buyer)
            saved += 1
        except Exception as e:
            logger.warning("cash_buyer save failed name={} error={}", buyer.get("name"), str(e))
    logger.info("cash_buyer_scraper saved {} buyers", saved)
    return saved


def _skip_trace_buyer(buyer):
    try:
        from backend.lib.batchdata import skip_trace_by_name_address
        name = buyer.get("name") or ""
        address = buyer.get("purchase_address") or ""
        if name and address:
            result = skip_trace_by_name_address(name=name, address=address)
            return result.get("phone") if result else None
    except Exception as e:
        logger.warning("cash_buyer skip_trace failed error={}", str(e))
    return None


def run_buyer_discovery(zip_codes=None):
    buyers = scrape_cash_buyers(zip_codes=zip_codes)
    return enrich_and_save_buyers(buyers)
