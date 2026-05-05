import os
from datetime import datetime, timedelta, timezone

from loguru import logger
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
        logger.info("Supabase client initialized")
    return _client


def upsert_property(data: dict) -> None:
    client = _get_client()
    client.table("properties").upsert(data, on_conflict="apn").execute()
    logger.debug("upsert_property apn={}", data.get("apn"))


def get_properties_by_score(min_score: int) -> list[dict]:
    client = _get_client()
    response = (
        client.table("properties")
        .select("*")
        .gte("distress_score", min_score)
        .order("distress_score", desc=True)
        .execute()
    )
    logger.debug("get_properties_by_score min={} count={}", min_score, len(response.data))
    return response.data


def get_new_properties_since(hours: int) -> list[dict]:
    client = _get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    response = (
        client.table("properties")
        .select("*")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .execute()
    )
    logger.debug("get_new_properties_since hours={} count={}", hours, len(response.data))
    return response.data


def insert_lead(property_id: str) -> str:
    client = _get_client()
    response = (
        client.table("leads")
        .insert({"property_id": property_id, "stage": "new"})
        .execute()
    )
    lead_id = response.data[0]["id"]
    logger.info("insert_lead property_id={} lead_id={}", property_id, lead_id)
    return lead_id


def get_lead_by_property(property_id: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*")
        .eq("property_id", property_id)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    logger.debug("get_lead_by_property property_id={} found={}", property_id, result is not None)
    return result


def update_lead_stage(lead_id: str, stage: str) -> None:
    client = _get_client()
    client.table("leads").update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", lead_id).execute()
    logger.info("update_lead_stage lead_id={} stage={}", lead_id, stage)


def insert_call(data: dict) -> None:
    client = _get_client()
    client.table("calls").insert(data).execute()
    logger.info("insert_call lead_id={}", data.get("lead_id"))


def insert_sms(data: dict) -> None:
    client = _get_client()
    client.table("sms_messages").insert(data).execute()
    logger.debug("insert_sms direction={}", data.get("direction"))


def get_leads_for_followup() -> list[dict]:
    client = _get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .in_("stage", ["new", "contacted"])
        .or_(f"last_contact_at.lte.{cutoff},last_contact_at.is.null")
        .order("distress_score", desc=True)
        .execute()
    )
    logger.debug("get_leads_for_followup count={}", len(response.data))
    return response.data


def get_property_by_id(property_id: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("properties")
        .select("*")
        .eq("id", property_id)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    logger.debug("get_property_by_id id={} found={}", property_id, result is not None)
    return result


def get_property_by_phone(phone: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("contacts")
        .select("*, properties(*)")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    logger.debug("get_property_by_phone phone={} found={}", phone, result is not None)
    return result


def insert_contact(data: dict) -> None:
    client = _get_client()
    client.table("contacts").insert(data).execute()
    logger.info("insert_contact property_id={}", data.get("property_id"))


def update_lead_contact_attempt(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "contact_attempts": client.table("leads").select("contact_attempts").eq("id", lead_id).execute().data[0]["contact_attempts"] + 1,
        "last_contact_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", lead_id).execute()
    logger.debug("update_lead_contact_attempt lead_id={}", lead_id)


def insert_comp(data: dict) -> None:
    client = _get_client()
    client.table("comps").insert(data).execute()
    logger.debug("insert_comp property_id={}", data.get("subject_property_id"))


def get_comps_by_property(property_id: str) -> list[dict]:
    client = _get_client()
    response = (
        client.table("comps")
        .select("*")
        .eq("subject_property_id", property_id)
        .order("sold_date", desc=True)
        .execute()
    )
    logger.debug("get_comps_by_property id={} count={}", property_id, len(response.data))
    return response.data


def update_property_arv(property_id: str, arv: int, mao: int, confidence: str) -> None:
    client = _get_client()
    client.table("properties").update({
        "estimated_arv": arv,
        "mao": mao,
        "arv_confidence": confidence,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", property_id).execute()
    logger.info("update_property_arv id={} arv={} mao={}", property_id, arv, mao)


def get_active_drip_leads() -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("opted_out", False)
        .eq("drip_paused", False)
        .eq("drip_completed", False)
        .execute()
    )
    rows = [r for r in response.data if r.get("drip_started_at")]
    logger.debug("get_active_drip_leads count={}", len(rows))
    return rows


def start_lead_drip(lead_id: str, sequence: str, drip_started_at: str, initial_day: int = 0) -> None:
    client = _get_client()
    client.table("leads").update({
        "drip_sequence": sequence,
        "drip_day": initial_day,
        "drip_started_at": drip_started_at,
        "drip_paused": False,
        "drip_completed": False,
        "opted_out": False,
        "last_sms_at": drip_started_at,
    }).eq("id", lead_id).execute()
    logger.info("start_lead_drip lead_id={} sequence={}", lead_id, sequence)


def update_lead_drip_progress(lead_id: str, drip_day: int, last_sms_at: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "drip_day": drip_day,
        "last_sms_at": last_sms_at,
    }).eq("id", lead_id).execute()
    logger.debug("update_lead_drip_progress lead_id={} day={}", lead_id, drip_day)


def mark_lead_opted_out(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "opted_out": True,
        "drip_paused": True,
    }).eq("id", lead_id).execute()
    logger.info("mark_lead_opted_out lead_id={}", lead_id)


def pause_lead_drip(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({"drip_paused": True}).eq("id", lead_id).execute()
    logger.info("pause_lead_drip lead_id={}", lead_id)


def complete_lead_drip(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({"drip_completed": True}).eq("id", lead_id).execute()
    logger.info("complete_lead_drip lead_id={}", lead_id)


def append_drip_reply(lead_id: str, reply: dict) -> None:
    client = _get_client()
    current = client.table("leads").select("drip_replies").eq("id", lead_id).execute()
    replies = (current.data[0].get("drip_replies") or []) if current.data else []
    replies.append(reply)
    client.table("leads").update({"drip_replies": replies}).eq("id", lead_id).execute()
    logger.debug("append_drip_reply lead_id={}", lead_id)


def get_lead_by_owner_phone(phone: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("owner_phone", phone)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    logger.debug("get_lead_by_owner_phone phone={} found={}", phone, result is not None)
    return result


def get_leads_for_drip_start(min_score: int) -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("opted_out", False)
        .execute()
    )
    return [
        r for r in response.data
        if not r.get("drip_started_at")
        and r.get("owner_phone")
        and (r.get("properties") or {}).get("distress_score", 0) >= min_score
    ]


def get_leads_for_outbound(min_score: int = 50) -> list[dict]:
    client = _get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("opted_out", False)
        .eq("callable", True)
        .eq("dnc_blocked", False)
        .or_(f"last_called_at.lte.{cutoff},last_called_at.is.null")
        .execute()
    )
    return [
        r for r in response.data
        if (r.get("properties") or {}).get("distress_score", 0) >= min_score
        and (r.get("properties") or {}).get("estimated_arv") is not None
        and (r.get("properties") or {}).get("callable_phones")
    ]


def get_lead_with_property(lead_id: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    logger.debug("get_lead_with_property id={} found={}", lead_id, result is not None)
    return result


def update_lead_call_outcome(lead_id: str, outcome: str, call_sid: str, duration: int = 0) -> None:
    client = _get_client()
    current = client.table("leads").select("call_attempts").eq("id", lead_id).execute()
    attempts = (current.data[0].get("call_attempts") or 0) + 1 if current.data else 1
    client.table("leads").update({
        "last_called_at": datetime.now(timezone.utc).isoformat(),
        "call_attempts": attempts,
        "last_call_outcome": outcome,
    }).eq("id", lead_id).execute()
    logger.info("update_lead_call_outcome lead_id={} outcome={} sid={}", lead_id, outcome, call_sid)


def schedule_callback(lead_id: str, callback_at: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "callback_scheduled_at": callback_at,
    }).eq("id", lead_id).execute()
    logger.info("schedule_callback lead_id={} at={}", lead_id, callback_at)
