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


def get_supabase() -> Client:
    return _get_client()


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


def insert_call(data: dict) -> str | None:
    client = _get_client()
    response = client.table("calls").insert(data).execute()
    call_id = response.data[0]["id"] if response.data else None
    logger.info("insert_call lead_id={} call_id={}", data.get("lead_id"), call_id)
    return call_id


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
        "email_day": -1,
        "email_paused": False,
        "email_completed": False,
        "last_email_at": drip_started_at,
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
    results = [
        r for r in response.data
        if (r.get("properties") or {}).get("distress_score", 0) >= min_score
        and (r.get("properties") or {}).get("estimated_arv") is not None
        and (r.get("properties") or {}).get("callable_phones")
    ]
    results.sort(
        key=lambda r: r.get("composite_score") or (r.get("properties") or {}).get("distress_score", 0),
        reverse=True,
    )
    return results


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


def update_lead_for_disposition(lead_id: str, disposition: str) -> None:
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    if disposition == "HOT":
        client.table("leads").update({
            "priority_callback": True,
            "updated_at": now,
        }).eq("id", lead_id).execute()
    elif disposition == "DEAD":
        client.table("leads").update({
            "opted_out": True,
            "drip_paused": True,
            "updated_at": now,
        }).eq("id", lead_id).execute()
    elif disposition == "COLD":
        current = client.table("leads").select("drip_day").eq("id", lead_id).execute()
        current_day = (current.data[0].get("drip_day") or -1) if current.data else -1
        if current_day < 30:
            client.table("leads").update({
                "drip_day": 30,
                "updated_at": now,
            }).eq("id", lead_id).execute()
    logger.info("update_lead_for_disposition lead_id={} disposition={}", lead_id, disposition)


def update_lead_appointment(lead_id: str, appointment_at: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "appointment_at": appointment_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    logger.info("update_lead_appointment lead_id={} at={}", lead_id, appointment_at)


def get_pending_appointment_leads() -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("stage", "walkthrough_booked")
        .not_.is_("appointment_at", "null")
        .execute()
    )
    logger.debug("get_pending_appointment_leads count={}", len(response.data))
    return response.data


def update_appt_reminder_flags(lead_id: str, day_before: bool | None = None, morning: bool | None = None, no_show: bool | None = None) -> None:
    client = _get_client()
    data = {}
    if day_before is not None:
        data["appt_day_before_sent"] = day_before
    if morning is not None:
        data["appt_morning_sent"] = morning
    if no_show is not None:
        data["appt_no_show_sent"] = no_show
    if data:
        client.table("leads").update(data).eq("id", lead_id).execute()
        logger.debug("update_appt_reminder_flags lead_id={}", lead_id)


def update_lead_speed_to_lead(lead_id: str, attempts: int, completed: bool = False) -> None:
    client = _get_client()
    client.table("leads").update({
        "speed_to_lead_attempts": attempts,
        "speed_to_lead_completed": completed,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    logger.debug("update_lead_speed_to_lead lead_id={} attempts={} completed={}", lead_id, attempts, completed)


def get_calls_for_lead(lead_id: str) -> list[dict]:
    client = _get_client()
    response = (
        client.table("calls")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .execute()
    )
    logger.debug("get_calls_for_lead lead_id={} count={}", lead_id, len(response.data))
    return response.data


def get_sms_for_lead(lead_id: str) -> list[dict]:
    client = _get_client()
    response = (
        client.table("sms_messages")
        .select("*")
        .eq("lead_id", lead_id)
        .order("sent_at", desc=True)
        .execute()
    )
    logger.debug("get_sms_for_lead lead_id={} count={}", lead_id, len(response.data))
    return response.data


def update_lead_engagement_scores(
    lead_id: str,
    recency: int,
    intensity: int,
    pattern: int,
    composite: float,
) -> None:
    client = _get_client()
    client.table("leads").update({
        "recency_score": recency,
        "intensity_score": intensity,
        "pattern_score": pattern,
        "composite_score": composite,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    logger.debug("update_lead_engagement_scores lead_id={} composite={}", lead_id, composite)


def update_lead_transcript_intel(lead_id: str, intel: dict) -> None:
    client = _get_client()
    data: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    field_map = {
        "motivation_level": "motivation_level",
        "seller_motivation": "seller_motivation",
        "price_floor": "price_floor",
        "timeline_urgency": "timeline_urgency",
        "hot_topics": "hot_topics",
        "rapport_openers": "rapport_openers",
        "competitor_mentions": "competitor_mentions",
        "next_best_action": "next_best_action",
        "call_summary": "call_summary",
    }
    for src, dst in field_map.items():
        val = intel.get(src)
        if val is not None:
            data[dst] = val
    client.table("leads").update(data).eq("id", lead_id).execute()
    logger.info("update_lead_transcript_intel lead_id={}", lead_id)


def get_active_email_leads() -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("opted_out", False)
        .eq("email_paused", False)
        .eq("email_completed", False)
        .not_.is_("owner_email", "null")
        .execute()
    )
    rows = [r for r in response.data if r.get("owner_email")]
    logger.debug("get_active_email_leads count={}", len(rows))
    return rows


def update_lead_email_progress(lead_id: str, email_day: int, last_email_at: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "email_day": email_day,
        "last_email_at": last_email_at,
    }).eq("id", lead_id).execute()
    logger.debug("update_lead_email_progress lead_id={} day={}", lead_id, email_day)


def pause_lead_email(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({"email_paused": True}).eq("id", lead_id).execute()
    logger.info("pause_lead_email lead_id={}", lead_id)


def complete_lead_email(lead_id: str) -> None:
    client = _get_client()
    client.table("leads").update({"email_completed": True}).eq("id", lead_id).execute()
    logger.info("complete_lead_email lead_id={}", lead_id)


def update_call_voicemail_script(lead_id: str, script_num: int) -> None:
    client = _get_client()
    response = (
        client.table("calls")
        .select("id")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        call_id = response.data[0]["id"]
        client.table("calls").update({"voicemail_script": script_num}).eq("id", call_id).execute()
        logger.debug("update_call_voicemail_script lead_id={} script={}", lead_id, script_num)


def mark_callback_from_voicemail(call_sid: str) -> None:
    client = _get_client()
    client.table("calls").update({"callback_from_voicemail": True}).eq(
        "signalwire_call_id", call_sid
    ).execute()
    logger.info("mark_callback_from_voicemail call_sid={}", call_sid)


def start_email_drip_for_lead(lead_id: str, started_at: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "email_day": -1,
        "email_paused": False,
        "email_completed": False,
        "last_email_at": started_at,
    }).eq("id", lead_id).execute()
    logger.info("start_email_drip_for_lead lead_id={}", lead_id)


def update_engagement_score(lead_id: str, event_type: str) -> None:
    client = _get_client()
    response = (
        client.table("leads")
        .select("recency_score,intensity_score,pattern_score,engagement_score,composite_score,last_contact_at,distress_score")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return

    row = response.data[0]
    recency = row.get("recency_score") or 0
    intensity = min(row.get("intensity_score") or 0, 40)
    pattern = min(row.get("pattern_score") or 0, 30)
    distress = row.get("distress_score") or 0

    event_intensity = {
        "sms_reply": 30,
        "call_answered": 20,
        "appointment_booked": 40,
        "callback_received": 40,
        "sms_opened": 5,
        "call_brief": 10,
        "no_contact_30d": 0,
    }
    event_pattern = {
        "sms_reply": 25,
        "call_answered": 15,
        "appointment_booked": 30,
        "callback_received": 30,
        "sms_opened": 0,
        "call_brief": 10,
        "no_contact_30d": 0,
    }

    if event_type == "no_contact_30d":
        recency = 2
    else:
        last_contact = row.get("last_contact_at")
        if last_contact:
            try:
                last_dt = datetime.fromisoformat(last_contact.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - last_dt).days
                if days < 7:
                    recency = 30
                elif days < 30:
                    recency = 20
                elif days < 90:
                    recency = 10
                else:
                    recency = 2
            except Exception:
                pass

    intensity = min(intensity + event_intensity.get(event_type, 0), 40)
    pattern = min(pattern + event_pattern.get(event_type, 0), 30)
    engagement = recency + intensity + pattern
    composite = min(round(distress * 0.5 + engagement * 0.5, 2), 100)

    client.table("leads").update({
        "recency_score": recency,
        "intensity_score": intensity,
        "pattern_score": pattern,
        "engagement_score": engagement,
        "composite_score": composite,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    logger.info("update_engagement_score lead_id={} event={} composite={}", lead_id, event_type, composite)


def insert_transcript_chunks(call_id: str, lead_id: str | None, chunks: list[dict]) -> None:
    if not chunks:
        return
    client = _get_client()
    rows = [
        {
            "call_id": call_id,
            "lead_id": lead_id,
            "speaker": c["speaker"],
            "text": c["text"],
            "chunk_type": c.get("chunk_type", "final"),
            "sequence_order": c["sequence_order"],
            "confidence": c.get("confidence"),
        }
        for c in chunks
    ]
    client.table("transcript_chunks").insert(rows).execute()
    logger.info("insert_transcript_chunks call_id={} count={}", call_id, len(rows))


def get_transcript_chunks(call_id: str) -> list[dict]:
    client = _get_client()
    response = (
        client.table("transcript_chunks")
        .select("*")
        .eq("call_id", call_id)
        .order("sequence_order")
        .execute()
    )
    logger.debug("get_transcript_chunks call_id={} count={}", call_id, len(response.data))
    return response.data


def reconstruct_transcript_from_chunks(call_id: str) -> str:
    chunks = get_transcript_chunks(call_id)
    if not chunks:
        return ""
    lines = [f"{c['speaker']}: {c['text']}" for c in chunks]
    return "\n".join(lines)


def insert_call_event(
    call_id: str,
    lead_id: str | None,
    event_type: str,
    payload: dict | None = None,
) -> None:
    client = _get_client()
    client.table("call_events").insert({
        "call_id": call_id,
        "lead_id": lead_id,
        "event_type": event_type,
        "payload": payload or {},
    }).execute()
    logger.debug("insert_call_event type={} call_id={}", event_type, call_id)


def update_call_intel(call_id: str, intel: dict) -> None:
    client = _get_client()
    call_fields = {
        "seller_name": "seller_name",
        "property_address": "property_address_mentioned",
        "asking_price": "asking_price",
        "occupancy": "occupancy",
        "property_condition": "property_condition",
        "distress_indicators": "distress_indicators",
        "objections": "objections",
        "appointment_interest": "appointment_interest",
        "next_step": "next_step",
        "followup_priority": "followup_priority",
        "extraction_confidence": "extraction_confidence",
        "seller_motivation": "seller_motivation",
        "motivation_confidence": "motivation_confidence",
        "timeline": "timeline",
        "lead_score": "lead_score",
        "call_summary": "call_summary",
    }
    data: dict = {}
    for src, dst in call_fields.items():
        val = intel.get(src)
        if val is not None:
            data[dst] = val
    if not data:
        return
    client.table("calls").update(data).eq("id", call_id).execute()
    logger.info("update_call_intel call_id={}", call_id)


def update_lead_intel_scores(lead_id: str, scores: dict) -> None:
    client = _get_client()
    data: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for key in ("followup_urgency", "is_hot_lead", "conversation_quality"):
        val = scores.get(key)
        if val is not None:
            data[key] = val
    if len(data) > 1:
        client.table("leads").update(data).eq("id", lead_id).execute()
        logger.info("update_lead_intel_scores lead_id={} hot={}", lead_id, scores.get("is_hot_lead"))
