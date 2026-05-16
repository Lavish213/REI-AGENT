import os
from datetime import datetime, timezone

from loguru import logger

from backend.lib.db import get_lead_by_owner_phone


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return "+" + digits if not digits.startswith("1") else "+1" + digits[-10:]


def _build_property_context_str(lead: dict) -> str:
    prop = lead.get("properties") or {}
    parts = []

    address = prop.get("address") or lead.get("address", "")
    if address:
        parts.append(f"Property: {address}")

    owner = lead.get("owner_first_name") or lead.get("owner_name", "")
    if owner:
        parts.append(f"Owner: {owner}")

    beds = prop.get("bedrooms")
    baths = prop.get("bathrooms")
    sqft = prop.get("sqft")
    year = prop.get("year_built")
    if any(v for v in [beds, baths, sqft, year]):
        desc_parts = []
        if beds:
            desc_parts.append(f"{beds}bd")
        if baths:
            desc_parts.append(f"{baths}ba")
        if sqft:
            desc_parts.append(f"{sqft}sqft")
        if year:
            desc_parts.append(f"built {year}")
        parts.append("Home: " + " / ".join(desc_parts))

    arv = prop.get("estimated_arv")
    if arv:
        parts.append(f"Est ARV: ${arv:,.0f}")

    distress = prop.get("distress_score")
    if distress:
        parts.append(f"Distress score: {distress}")

    stage = lead.get("stage", "")
    if stage:
        parts.append(f"Stage: {stage}")

    notes = lead.get("notes", "").strip()
    if notes:
        parts.append(f"Notes: {notes[:200]}")

    if not parts:
        return "No property context available."

    return "\n".join(parts)


def preload_call_context(caller_phone: str) -> dict:
    """
    Look up lead by caller phone. Returns context dict consumed by agent.py.
    Called in threadpool by webhook.py before WebSocket connect.
    """
    try:
        lead = get_lead_by_owner_phone(caller_phone)
    except Exception as e:
        logger.error("preload_call_context db error phone={} error={}", caller_phone, str(e))
        lead = None

    if not lead:
        logger.info("preload_call_context no lead found phone={}", caller_phone)
        return {
            "lead": None,
            "property_context_str": "No property context available. Greet warmly and ask if they are calling about selling their home.",
            "owner_first_name": "there",
        }

    property_context_str = _build_property_context_str(lead)
    owner_first_name = (
        lead.get("owner_first_name")
        or lead.get("owner_name", "").split()[0]
        or "there"
    )

    logger.info(
        "preload_call_context found lead_id={} phone={}",
        lead.get("id"),
        caller_phone,
    )

    return {
        "lead": lead,
        "property_context_str": property_context_str,
        "owner_first_name": owner_first_name,
    }


def preload_boss_context() -> dict:
    """
    Returns boss-mode context for owner check-in calls.
    """
    now = datetime.now(timezone.utc).strftime("%A %B %d, %Y %H:%M UTC")
    briefing = f"Check-in call at {now}."

    return {
        "lead": None,
        "property_context_str": "",
        "owner_first_name": "Angelo",
        "briefing": briefing,
    }
