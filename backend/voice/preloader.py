from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger

from backend.lib.db import get_lead_by_owner_phone


_INITIAL_TRUST_BY_SOURCE: dict[str, float] = {
    "web_form_inbound": 7.0,
    "website": 7.0,
    "referral": 7.5,
    "direct_mail": 6.0,
    "direct_mail_callback": 6.0,
    "cold_list_absentee": 4.5,
    "cold_list": 4.5,
    "preforeclosure": 4.0,
    "probate": 5.0,
    "inherited": 5.0,
    "tired_landlord": 5.0,
}

_DEFAULT_TRUST = 5.0

_SITUATION_BY_SOURCE: dict[str, str] = {
    "preforeclosure": "preforeclosure",
    "probate": "probate",
    "inherited": "inherited_property",
    "tired_landlord": "tired_landlord",
}

_SITUATION_BY_TAG: dict[str, str] = {
    "inherited": "inherited_property",
    "probate": "probate",
    "preforeclosure": "preforeclosure",
    "foreclosure": "preforeclosure",
    "divorce": "divorce",
    "landlord": "tired_landlord",
    "vacant": "vacant_property",
    "relocation": "relocation",
    "downsizing": "downsizing",
}


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())

    if not digits:
        return ""
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def _detect_situation(lead: dict) -> str:
    source = (lead.get("source") or "").lower()
    tags = lead.get("tags") or []

    if isinstance(tags, str):
        tags = [tags]

    tags_lower = [t.lower() for t in tags]

    if source in _SITUATION_BY_SOURCE:
        return _SITUATION_BY_SOURCE[source]

    for tag in tags_lower:
        for key, situation in _SITUATION_BY_TAG.items():
            if key in tag:
                return situation

    notes = (lead.get("notes") or "").lower()
    if "inherited" in notes or "passed away" in notes:
        return "inherited_property"
    if "probate" in notes:
        return "probate"
    if "foreclosure" in notes:
        return "preforeclosure"
    if "divorce" in notes:
        return "divorce"
    if "landlord" in notes or "tenant" in notes:
        return "tired_landlord"

    return "unknown"


def _get_initial_trust(lead: dict) -> float:
    source = (lead.get("source") or "").lower()
    return _INITIAL_TRUST_BY_SOURCE.get(source, _DEFAULT_TRUST)


def _build_property_context_str(lead: dict) -> str:
    property_data = lead.get("properties") or {}
    parts: list[str] = []

    address = property_data.get("address") or lead.get("address", "")
    if address:
        parts.append(f"Property: {address}")

    owner_name = lead.get("owner_first_name") or lead.get("owner_name", "")
    if owner_name:
        parts.append(f"Owner: {owner_name}")

    bedrooms = property_data.get("bedrooms")
    bathrooms = property_data.get("bathrooms")
    sqft = property_data.get("sqft")
    year_built = property_data.get("year_built")

    if any(v is not None for v in (bedrooms, bathrooms, sqft, year_built)):
        home_parts: list[str] = []
        if bedrooms:
            home_parts.append(f"{bedrooms}bd")
        if bathrooms:
            home_parts.append(f"{bathrooms}ba")
        if sqft:
            home_parts.append(f"{sqft}sqft")
        if year_built:
            home_parts.append(f"built {year_built}")
        if home_parts:
            parts.append("Home: " + " / ".join(home_parts))

    arv = property_data.get("estimated_arv")
    if arv:
        try:
            parts.append(f"Est ARV: ${float(arv):,.0f}")
        except Exception:
            pass

    distress_score = property_data.get("distress_score")
    if distress_score:
        parts.append(f"Distress score: {distress_score}")

    stage = lead.get("stage")
    if stage:
        parts.append(f"Stage: {stage}")

    notes = (lead.get("notes") or "").strip()
    if notes:
        parts.append(f"Notes: {' '.join(notes.split())[:250]}")

    return "\n".join(parts) if parts else "No property context available."


def preload_call_context(caller_phone: str) -> dict:
    normalized_phone = _normalize_phone(caller_phone)

    try:
        lead = get_lead_by_owner_phone(normalized_phone)
    except Exception as e:
        logger.error(
            "preload_call_context db_error phone={} error={}",
            normalized_phone,
            str(e),
        )
        lead = None

    if not lead:
        logger.info("preload_call_context lead_not_found phone={}", normalized_phone)
        return {
            "lead": None,
            "is_outbound": False,
            "address": "",
            "property_context_str": "No property context available.",
            "owner_first_name": "",
            "normalized_phone": normalized_phone,
            "situation_label": "unknown",
            "initial_trust_score": _DEFAULT_TRUST,
        }

    property_data = lead.get("properties") or {}
    address = property_data.get("address", "")

    owner_first_name = (
        lead.get("owner_first_name")
        or ((lead.get("owner_name") or "").split(" ")[0])
        or ""
    )

    property_context_str = _build_property_context_str(lead)
    situation_label = _detect_situation(lead)
    initial_trust_score = _get_initial_trust(lead)

    seller_memory = None
    memory_context_str = ""
    try:
        from backend.voice.memory import SellerMemory
        seller_memory = SellerMemory.load(lead["id"])
        memory_context_str = seller_memory.to_prompt_context()
    except Exception as e:
        logger.warning("preload seller_memory failed error={}", str(e))

    logger.info(
        "preload_call_context lead_found lead_id={} phone={} "
        "situation={} trust={:.1f}",
        lead.get("id"),
        normalized_phone,
        situation_label,
        initial_trust_score,
    )

    return {
        "lead": lead,
        "is_outbound": False,
        "address": address,
        "property_context_str": property_context_str,
        "owner_first_name": owner_first_name,
        "normalized_phone": normalized_phone,
        "situation_label": situation_label,
        "initial_trust_score": initial_trust_score,
        "seller_memory": seller_memory,
        "memory_context_str": memory_context_str,
    }


def preload_boss_context() -> dict:
    now = datetime.now(UTC).strftime("%A %B %d, %Y %H:%M UTC")
    briefing = f"Owner check-in call at {now}."

    logger.info("preload_boss_context initialized")

    return {
        "lead": None,
        "is_outbound": False,
        "address": "",
        "property_context_str": "",
        "owner_first_name": "Angelo",
        "briefing": briefing,
        "normalized_phone": "",
        "situation_label": "unknown",
        "initial_trust_score": _DEFAULT_TRUST,
    }