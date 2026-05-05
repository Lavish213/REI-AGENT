import os
from datetime import datetime, timedelta, timezone
from loguru import logger

from backend.lib.db import (
    get_property_by_phone,
    get_comps_by_property,
    get_lead_by_property,
    _get_client as _db,
)
from backend.comps.redfin import get_comps
from backend.comps.calculator import calculate_arv
from backend.comps.cache import get_cached_comps, set_cached_comps
from backend.lib.db import update_property_arv, insert_comp
from backend.lib.osm import enrich_property_full


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

    osm_data = enrich_property_full(
        prop.get("address", ""),
        prop.get("city", ""),
        prop.get("state", "CA"),
    )
    context["property_context_str"] = _build_property_context_str(context, osm_data)
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


def _build_property_context_str(ctx: dict, osm_data: dict | None = None) -> str:
    prop = ctx.get("property") or {}
    arv = _dollars(ctx.get("arv"))
    mao = _dollars(ctx.get("mao"))
    confidence = ctx.get("arv_confidence", "low")
    owner = ctx.get("owner_name", "Unknown")
    first_name = ctx.get("owner_first_name", "there")
    osm = osm_data or {}

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

    cross = osm.get("cross_streets", [])
    cross_str = (
        f"near {cross[0]} and {cross[1]}" if len(cross) >= 2
        else f"near {cross[0]}" if cross
        else "unknown"
    )

    neighborhood = osm.get("neighborhood") or prop.get("city", "")
    district = osm.get("school_district", "unknown")
    district_desc = osm.get("school_district_description", "")
    district_line = f"{district} ({district_desc})" if district_desc else district

    arv_min = osm.get("arv_min")
    arv_max = osm.get("arv_max")
    arv_range_str = (
        f"${arv_min:,} - ${arv_max:,}" if arv_min and arv_max else "unknown"
    )

    flood_zone = osm.get("flood_zone", "unknown")
    flood_risk = osm.get("flood_risk", "unknown")
    flood_line = f"Zone {flood_zone} — {flood_risk}" if flood_zone != "unknown" else "unknown"

    ace_miles = osm.get("ace_miles")
    ace_station = osm.get("ace_station", "")
    ace_accessible = osm.get("ace_accessible", False)
    if ace_miles is not None:
        ace_line = f"{ace_miles} miles to {ace_station} Station"
        if ace_accessible:
            ace_line += " (ACE-accessible — Bay Area commuter appeal)"
    else:
        ace_line = "unknown"

    buy_box = osm.get("buy_box", "unknown")
    nbhd_notes = osm.get("neighborhood_notes", "")

    landmarks = osm.get("landmarks", [])
    landmarks_str = ", ".join(landmarks[:3]) if landmarks else "none found"

    return f"""
CALLER PROPERTY CONTEXT
=======================
Owner: {owner} (call them {first_name})
Address: {prop.get("address", "unknown")} {prop.get("city", "")} {prop.get("zip", "")}
Cross Streets: {cross_str}
Neighborhood: {neighborhood}
Beds/Baths: {prop.get("beds", "?")} bed / {prop.get("baths", "?")} bath
Sqft: {prop.get("sqft", "unknown")}
Year Built: {prop.get("year_built", "unknown")}
Distress Type: {distress}
Equity: {equity_str}
Tax Delinquent: {_dollars(prop.get("tax_delinquent_amount"))}
Auction Date: {auction_str}
Nearby: {landmarks_str}

LOCATION INTELLIGENCE
=====================
School District: {district_line}
ARV Range for Area: {arv_range_str}
Flood Zone: {flood_line}
ACE Train: {ace_line}
Buy Box Fit: {buy_box}
Notes: {nbhd_notes}

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


def preload_boss_context() -> dict:
    logger.info("preload_boss_context loading pipeline briefing")

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()

    db = _db()

    calls_today = db.table("calls").select("id", count="exact").gte("created_at", today_start).execute()
    calls_week = db.table("calls").select("id", count="exact").gte("created_at", week_start).execute()

    leads_week = db.table("leads").select("id", count="exact").gte("created_at", week_start).execute()

    hot_props = (
        db.table("properties")
        .select("address, city, distress_score, distress_type, estimated_arv, mao")
        .gte("distress_score", 85)
        .order("distress_score", desc=True)
        .limit(3)
        .execute()
    )

    appointments = (
        db.table("leads")
        .select("id, properties(address, city)")
        .eq("stage", "appointment_scheduled")
        .execute()
    )

    top_leads = (
        db.table("leads")
        .select("id, stage, properties(address, city, distress_score, distress_type, estimated_arv, mao)")
        .in_("stage", ["new", "contacted", "appointment_scheduled", "negotiating"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )

    active_with_props = [
        r for r in (top_leads.data or [])
        if r.get("properties") and r["properties"].get("distress_score")
    ]
    active_with_props.sort(key=lambda r: r["properties"]["distress_score"], reverse=True)
    top_3 = active_with_props[:3]

    pipeline_mao_total = sum(
        (r["properties"].get("mao") or 0)
        for r in active_with_props
        if r.get("properties")
    )

    briefing = _build_boss_briefing(
        calls_today=calls_today.count or 0,
        calls_week=calls_week.count or 0,
        leads_week=leads_week.count or 0,
        hot_props=hot_props.data or [],
        appointments=appointments.data or [],
        top_3=top_3,
        pipeline_mao_total=pipeline_mao_total,
        active_count=len(active_with_props),
    )

    logger.info("boss briefing built calls_today={} leads_week={}", calls_today.count, leads_week.count)
    return {
        "boss_mode": True,
        "briefing": briefing,
        "property_context_str": briefing,
        "lead": None,
        "owner_first_name": "Alanzo",
    }


def _build_boss_briefing(
    calls_today: int,
    calls_week: int,
    leads_week: int,
    hot_props: list,
    appointments: list,
    top_3: list,
    pipeline_mao_total: int,
    active_count: int,
) -> str:
    lines = ["Boss mode active. Here is your update:"]

    lines.append(
        f"This week Sophia handled {calls_week} calls and created {leads_week} leads. "
        f"{calls_today} calls came in today."
    )

    if top_3:
        top = top_3[0]["properties"]
        arv_str = _dollars(top.get("estimated_arv"))
        mao_str = _dollars(top.get("mao"))
        distress = (top.get("distress_type") or "unknown").replace("_", " ")
        lines.append(
            f"Top lead: {top.get('address')}, {top.get('city')} "
            f"scoring {top.get('distress_score')}, {distress}, "
            f"estimated ARV {arv_str}, MAO {mao_str}."
        )

    if appointments:
        for appt in appointments:
            prop = appt.get("properties") or {}
            addr = prop.get("address") or "unknown address"
            city = prop.get("city") or ""
            lines.append(f"You have a walkthrough scheduled at {addr}, {city}.")

    if hot_props:
        for hp in hot_props:
            lines.append(
                f"Hot alert — {hp.get('address')}, {hp.get('city')} "
                f"just came in at score {hp.get('distress_score')}."
            )

    pipeline_str = _dollars(pipeline_mao_total) if pipeline_mao_total else "$0"
    lines.append(
        f"Pipeline has {active_count} active leads worth {pipeline_str} combined."
    )

    lines.append("What do you want me to focus on?")

    return "\n".join(lines)
