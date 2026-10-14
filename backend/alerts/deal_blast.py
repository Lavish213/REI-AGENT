from __future__ import annotations
import os
from datetime import datetime, timezone
from loguru import logger


def blast_deal(property_id: str, operator_notes: str = "") -> dict:
    logger.warning("deal_blast_blocked property_id={} reason=missing_verified_buyer_campaign_authority", property_id)
    return {"sms": 0, "email": 0, "status": "blocked", "reason": "Buyer campaigns require verified property pricing and campaign authority"}


def _filter_eligible_buyers(buyers: list[dict], city: str, mao: int) -> list[dict]:
    eligible = []
    city_lower = city.lower()
    for b in buyers:
        max_price = b.get("max_price") or 0
        if max_price and mao and max_price < mao:
            continue
        preferred = b.get("preferred_cities") or []
        if preferred and city_lower not in [c.lower() for c in preferred]:
            continue
        eligible.append(b)
    return eligible


def _send_buyer_sms(to, first_name, address, city, mao, arv, beds, baths, sqft, operator_notes, buyer_id) -> bool:
    from backend.alerts.sms import send_sms
    mao_fmt = f"${mao / 100:,.2f}" if mao else "TBD"
    arv_fmt = f"${arv / 100:,.2f}" if arv else "TBD"
    notes = f" Note: {operator_notes}" if operator_notes else ""
    body = (
        f"Hey {first_name} — Sophia from SJ House Buyers. "
        f"New deal in {city}: {address}, {beds}bd/{baths}ba, ~{sqft} sqft. "
        f"ARV {arv_fmt}, asking {mao_fmt}.{notes} "
        f"Interested? Reply YES. Reply STOP to opt out."
    )
    sent = send_sms(to=to, body=body, lead_id=buyer_id)
    logger.info("deal_blast_sms buyer_id={} sent={}", buyer_id, sent)
    return sent


def _send_buyer_email(to, first_name, address, city, mao, arv, beds, baths, sqft, operator_notes, property_id) -> bool:
    from backend.alerts.email import send_email
    mao_fmt = f"${mao / 100:,.2f}" if mao else "TBD"
    arv_fmt = f"${arv / 100:,.2f}" if arv else "TBD"
    agent_ph = os.environ.get("AGENT_PHONE", "")
    from_name = os.environ.get("BUSINESS_NAME", "San Joaquin House Buyers")
    subject = f"New Deal Available — {address}, {city}"
    body_plain = (
        f"Hey {first_name},\n\nNew deal just came in:\n\n"
        f"Address: {address}, {city}, CA\n"
        f"Beds/Baths: {beds}bd / {baths}ba\n"
        f"Sq Ft: {sqft}\n"
        f"ARV: {arv_fmt}\n"
        f"Asking Price: {mao_fmt}\n"
        f"Condition: As-is\n"
        f"Close Timeline: 14-21 days\n"
        + (f"\nNotes: {operator_notes}\n" if operator_notes else "")
        + f"\nReply or call/text {agent_ph} to move forward.\n\n— Sophia\n{from_name}"
    )
    sg_id = send_email(to=to, subject=subject, body=body_plain)
    logger.info("deal_blast_email to={} sent={}", to, sg_id is not None)
    return bool(sg_id)


def upsert_cash_buyer(data: dict) -> str | None:
    from backend.lib.db import _get_client
    phone = data.get("owner_phone", "")
    email = data.get("owner_email", "")
    name = data.get("owner_name", "")
    if not phone and not email:
        logger.warning("upsert_cash_buyer no contact info name={}", name)
        return None
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "owner_name": name,
        "owner_phone": phone or None,
        "owner_email": email or None,
        "source": data.get("source", "deed_record"),
        "preferred_cities": data.get("preferred_cities", []),
        "max_price": data.get("max_price"),
        "transaction_count": data.get("transaction_count", 0),
        "opted_out": False,
        "updated_at": now,
    }
    lookup_key = phone or email
    lookup_col = "owner_phone" if phone else "owner_email"
    existing = client.table("cash_buyers").select("id").eq(lookup_col, lookup_key).limit(1).execute()
    if existing.data:
        buyer_id = existing.data[0]["id"]
        client.table("cash_buyers").update(record).eq("id", buyer_id).execute()
        logger.debug("cash_buyer_updated id={}", buyer_id)
        return buyer_id
    record["created_at"] = now
    resp = client.table("cash_buyers").insert(record).execute()
    buyer_id = resp.data[0]["id"] if resp.data else None
    logger.info("cash_buyer_created id={} name={}", buyer_id, name)
    return buyer_id
