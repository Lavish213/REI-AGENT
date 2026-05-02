import os
from datetime import datetime, timezone
from loguru import logger

from backend.lib.db import (
    get_property_by_phone,
    get_comps_by_property,
    get_lead_by_property,
)
from backend.comps.redfin import get_comps
from backend.comps.calculator import calculate_arv
from backend.comps.cache import get_cached_comps, set_cached_comps
from backend.lib.db import update_property_arv, insert_comp


def preload_call_context(caller_phone: str) -> dict:
    logger.info("preload_call_context phone={}", caller_phone)

    context = {
        "caller_phone": caller_phone,
        "property": None,
        "lead": None,
        "comps": [],
        "arv": None,
        "mao": None,
        "arv_confidence": "low",
        "owner_name": None,
        "owner_first_name": None,
        "property_context_str": "",
    }

    contact_record = get_property_by_phone(caller_phone)
    if not contact_record:
        logger.warning("no property found for phone={}", caller_phone)
        context["property_context_str"] = _build_unknown_caller_context(caller_phone)
        return context

    prop = contact_record.get("properties")
    if not prop:
        logger.warning("contact found but no property linked phone={}", caller_phone)
        context["property_context_str"] = _build_unknown_caller_context(caller_phone)
        return context

    context["property"] = prop
    context["owner_name"] = contact_record.get("owner_name") or prop.get("owner_name")

    if context["owner_name"]:
        parts = context["owner_name"].strip().split()
        context["owner_first_name"] = parts[0].title() if parts else None

    lead = get_lead_by_property(prop["id"])
    context["lead"] = lead

    cached_comps = get_cached_comps(
        prop.get("address", ""),
        prop.get("city", ""),
        prop.get("state", "CA"),
    )

    if cached_comps:
        comps = cached_comps
    else:
        comps = get_comps(
            address=prop.get("address", ""),
            city=prop.get("city", ""),
            state=prop.get("state", "CA"),
            beds=prop.get("beds"),
            baths=prop.get("baths"),
            sqft=prop.get("sqft"),
        )
        if comps:
            set_cached_comps(
                prop.get("address", ""),
                prop.get("city", ""),
                prop.get("state", "CA"),
                comps,
            )

    context["comps"] = comps

    arv_result = calculate_arv(comps, prop.get("sqft"))
    context["arv"] = arv_result["arv"]
    context["mao"] = arv_result["mao"]
    context["arv_confidence"] = arv_result["confidence"]

    if arv_result["arv"] and prop.get("id"):
        update_property_arv(
            prop["id"],
            arv_result["arv"],
            arv_result["mao"],
            arv_result["confidence"],
        )

    context["property_context_str"] = _build_property_context_str(context)
    logger.info(
        "preload complete phone={} address={} arv={} mao={} confidence={}",
        caller_phone,
        prop.get("address"),
        arv_result["arv"],
        arv_result["mao"],
        arv_result["confidence"],
    )
    return context


def _dollars(cents: int | None) -> str:
    if cents is None:
        return "unknown"
    return f"${cents / 100:,.0f}"


def _build_property_context_str(ctx: dict) -> str:
    prop = ctx.get("property") or {}
    arv = _dollars(ctx.get("arv"))
    mao = _dollars(ctx.get("mao"))
    confidence = ctx.get("arv_confidence", "low")
    owner = ctx.get("owner_name", "Unknown")
    first_name = ctx.get("owner_first_name", "there")

    auction_date = prop.get("auction_date")
    if auction_date:
        try:
            from datetime import datetime
            for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                try:
                    dt = datetime.strptime(auction_date, fmt).replace(tzinfo=timezone.utc)
                    days = (dt - datetime.now(timezone.utc)).days
                    auction_str = f"{auction_date} ({days} days away)"
                    break
                except ValueError:
                    continue
            else:
                auction_str = auction_date
        except Exception:
            auction_str = auction_date
    else:
        auction_str = "none on file"

    distress = prop.get("distress_type", "unknown").replace("_", " ").title()
    equity = prop.get("equity_pct")
    equity_str = f"{equity:.0f}%" if equity else "unknown"

    return f"""
CALLER PROPERTY CONTEXT
=======================
Owner: {owner} (call them {first_name})
Address: {prop.get("address", "unknown")} {prop.get("city", "")} {prop.get("zip", "")}
Beds/Baths: {prop.get("beds", "?")} bed / {prop.get("baths", "?")} bath
Sqft: {prop.get("sqft", "unknown")}
Year Built: {prop.get("year_built", "unknown")}
Distress Type: {distress}
Equity: {equity_str}
Tax Delinquent: {_dollars(prop.get("tax_delinquent_amount"))}
Auction Date: {auction_str}

PRICING
=======
Estimated ARV: {arv} (confidence: {confidence})
Your Max Offer (MAO): {mao}
Comp Count: {len(ctx.get("comps", []))}

OFFER GUIDANCE
==============
Start verbal offer range ABOVE MAO
Target: anchor at ARV x 0.75 then negotiate down
Never reveal the MAO number directly
If seller says they need more than MAO: escalate to Alanzo
If confidence is low: widen your range and caveat with walkthrough
""".strip()


def _build_unknown_caller_context(phone: str) -> str:
    return f"""
CALLER PROPERTY CONTEXT
=======================
No property found for this number: {phone}
This may be a new inbound lead or wrong number.
Greet warmly, ask if they are calling about selling their home.
Gather: full address, their name, reason for calling.
Do not make any offer — gather info only and tell them
Alanzo will follow up with a number after reviewing the property.
""".strip()
