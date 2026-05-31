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


# ──────────────────────────────────────────────────────────────────
# Batch D — Workflow + Followup runtime
# ──────────────────────────────────────────────────────────────────

def insert_workflow_transition(
    lead_id: str,
    state: str,
    trigger_source: str = "system",
    triggered_by: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Append workflow transition to audit log, update leads.workflow_state.
    Returns True if the state actually changed."""
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()

    current = client.table("leads").select("workflow_state").eq("id", lead_id).limit(1).execute()
    previous_state = (current.data[0].get("workflow_state") or "new_lead") if current.data else "new_lead"
    state_changed = previous_state != state

    client.table("workflows").insert({
        "lead_id": lead_id,
        "state": state,
        "previous_state": previous_state,
        "trigger_source": trigger_source,
        "triggered_by": triggered_by,
        "metadata": metadata or {},
    }).execute()

    client.table("leads").update({
        "workflow_state": state,
        "workflow_updated_at": now,
        "updated_at": now,
    }).eq("id", lead_id).execute()

    logger.info(
        "workflow_transition lead_id={} {}→{} source={}",
        lead_id, previous_state, state, trigger_source,
    )
    return state_changed


def get_lead_workflow_history(lead_id: str, limit: int = 20) -> list[dict]:
    client = _get_client()
    response = (
        client.table("workflows")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data


def create_followup(
    lead_id: str,
    call_id: str | None = None,
    priority: str = "medium",
    followup_type: str = "call",
    notes: str | None = None,
    scheduled_at: str | None = None,
    created_by: str = "system",
) -> str | None:
    client = _get_client()
    response = client.table("followups").insert({
        "lead_id": lead_id,
        "call_id": call_id,
        "priority": priority,
        "followup_type": followup_type,
        "state": "pending",
        "notes": notes,
        "scheduled_at": scheduled_at,
        "created_by": created_by,
    }).execute()
    followup_id = response.data[0]["id"] if response.data else None
    logger.info("create_followup lead_id={} priority={} id={}", lead_id, priority, followup_id)
    return followup_id


def get_pending_followups(limit: int = 50) -> list[dict]:
    client = _get_client()
    response = (
        client.table("followups")
        .select("*, leads(id, address, workflow_state, is_hot_lead, motivation_level)")
        .eq("state", "pending")
        .order("priority")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    rows = response.data
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (priority_rank.get(r.get("priority", "low"), 3), r.get("created_at", "")))
    logger.debug("get_pending_followups count={}", len(rows))
    return rows


def complete_followup(followup_id: str) -> None:
    client = _get_client()
    client.table("followups").update({
        "state": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", followup_id).execute()
    logger.info("complete_followup id={}", followup_id)


def cancel_followup(followup_id: str) -> None:
    client = _get_client()
    client.table("followups").update({"state": "cancelled"}).eq("id", followup_id).execute()
    logger.info("cancel_followup id={}", followup_id)


def get_hot_leads_queue(limit: int = 25) -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("id, workflow_state, stage, motivation_level, timeline_urgency, followup_urgency, call_summary, is_hot_lead, properties(address, distress_score, estimated_arv, mao)")
        .eq("is_hot_lead", True)
        .neq("workflow_state", "dead_lead")
        .neq("stage", "dead")
        .order("followup_urgency", desc=True)
        .limit(limit)
        .execute()
    )
    logger.debug("get_hot_leads_queue count={}", len(response.data))
    return response.data


def get_appointment_queue(limit: int = 25) -> list[dict]:
    client = _get_client()
    response = (
        client.table("leads")
        .select("id, appointment_at, workflow_state, stage, appt_day_before_sent, appt_morning_sent, appt_no_show_sent, properties(address)")
        .in_("stage", ["walkthrough_booked"])
        .not_.is_("appointment_at", "null")
        .order("appointment_at")
        .limit(limit)
        .execute()
    )
    logger.debug("get_appointment_queue count={}", len(response.data))
    return response.data


def get_workflow_activity(limit: int = 50) -> list[dict]:
    client = _get_client()
    response = (
        client.table("call_events")
        .select("id, event_type, payload, created_at, lead_id, call_id")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    logger.debug("get_workflow_activity count={}", len(response.data))
    return response.data


def get_pipeline_by_workflow_state() -> dict:
    client = _get_client()
    states = [
        "new_lead", "active_contact", "followup_required",
        "appointment_pending", "appointment_confirmed",
        "negotiation", "under_review", "dead_lead", "closed",
    ]
    result = {}
    for state in states:
        resp = (
            client.table("leads")
            .select("id", count="exact")
            .eq("workflow_state", state)
            .execute()
        )
        result[state] = resp.count or 0
    return result


def escalate_lead(lead_id: str, notes: str | None = None) -> None:
    client = _get_client()
    data: dict = {
        "escalated": True,
        "priority_callback": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        data["operator_notes"] = notes
    client.table("leads").update(data).eq("id", lead_id).execute()
    logger.info("escalate_lead lead_id={}", lead_id)


def update_operator_notes(lead_id: str, notes: str) -> None:
    client = _get_client()
    client.table("leads").update({
        "operator_notes": notes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    logger.info("update_operator_notes lead_id={}", lead_id)


# ──────────────────────────────────────────────────────────────────
# Batch E — Offers + Walkthroughs + Analytics
# ──────────────────────────────────────────────────────────────────

def create_offer(
    lead_id: str,
    arv_used: int | None,
    repair_estimate: int = 2500000,
    offer_amount: int | None = None,
    property_id: str | None = None,
    notes: str | None = None,
    created_by: str = "operator",
) -> str | None:
    """Create offer record. MAO = (arv_used * 0.70) - repair_estimate."""
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    mao_calculated: int | None = None
    if arv_used is not None:
        mao_calculated = int(arv_used * 0.70) - repair_estimate

    response = client.table("offers").insert({
        "lead_id": lead_id,
        "property_id": property_id,
        "arv_used": arv_used,
        "repair_estimate": repair_estimate,
        "mao_calculated": mao_calculated,
        "offer_amount": offer_amount if offer_amount is not None else mao_calculated,
        "offer_status": "draft",
        "notes": notes,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }).execute()
    offer_id = response.data[0]["id"] if response.data else None
    logger.info("create_offer lead_id={} mao={} id={}", lead_id, mao_calculated, offer_id)
    return offer_id


def get_offer_by_id(offer_id: str) -> dict | None:
    client = _get_client()
    response = (
        client.table("offers")
        .select("*")
        .eq("id", offer_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_offers_for_lead(lead_id: str) -> list[dict]:
    client = _get_client()
    response = (
        client.table("offers")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .execute()
    )
    logger.debug("get_offers_for_lead lead_id={} count={}", lead_id, len(response.data))
    return response.data


def update_offer_status(offer_id: str, status: str, notes: str | None = None) -> None:
    client = _get_client()
    data: dict = {
        "offer_status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes is not None:
        data["notes"] = notes
    client.table("offers").update(data).eq("id", offer_id).execute()
    logger.info("update_offer_status id={} status={}", offer_id, status)


def update_walkthrough_state(
    lead_id: str,
    state: str,
    notes: str | None = None,
    completed_at: str | None = None,
) -> None:
    client = _get_client()
    data: dict = {
        "walkthrough_state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes is not None:
        data["walkthrough_notes"] = notes
    if completed_at is not None:
        data["walkthrough_completed_at"] = completed_at
    elif state == "completed" and completed_at is None:
        data["walkthrough_completed_at"] = datetime.now(timezone.utc).isoformat()
    client.table("leads").update(data).eq("id", lead_id).execute()
    logger.info("update_walkthrough_state lead_id={} state={}", lead_id, state)


def get_workflow_analytics() -> dict:
    """Comprehensive analytics snapshot for the analytics dashboard."""
    client = _get_client()
    now = datetime.now(timezone.utc)

    # Pipeline by workflow state
    workflow_states = [
        "new_lead", "active_contact", "followup_required",
        "appointment_pending", "appointment_confirmed",
        "negotiation", "under_review", "dead_lead", "closed",
    ]
    workflow_pipeline: dict[str, int] = {}
    for state in workflow_states:
        r = client.table("leads").select("id", count="exact").eq("workflow_state", state).execute()
        workflow_pipeline[state] = r.count or 0

    # Stage pipeline (legacy)
    stages = ["new", "contacted", "offer_made", "walkthrough_booked", "under_contract", "closed", "dead"]
    stage_pipeline: dict[str, int] = {}
    for stage in stages:
        r = client.table("leads").select("id", count="exact").eq("stage", stage).execute()
        stage_pipeline[stage] = r.count or 0

    # Disposition breakdown from calls (last 30 days)
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    calls_resp = (
        client.table("calls")
        .select("call_disposition")
        .gte("created_at", cutoff_30d)
        .execute()
    )
    disposition_counts: dict[str, int] = {"HOT": 0, "WARM": 0, "COLD": 0, "DEAD": 0, "unknown": 0}
    for call in (calls_resp.data or []):
        d = (call.get("call_disposition") or "unknown").upper()
        if d not in disposition_counts:
            d = "unknown"
        disposition_counts[d] += 1

    # Hot leads
    hot_resp = (
        client.table("leads")
        .select("id", count="exact")
        .eq("is_hot_lead", True)
        .neq("workflow_state", "dead_lead")
        .execute()
    )
    hot_count = hot_resp.count or 0

    # Followup queue by priority
    followup_resp = client.table("followups").select("priority").eq("state", "pending").execute()
    followup_by_priority: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for f in (followup_resp.data or []):
        p = f.get("priority", "low")
        followup_by_priority[p] = followup_by_priority.get(p, 0) + 1

    # Calls this week
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    calls_week_resp = (
        client.table("calls")
        .select("id", count="exact")
        .gte("created_at", cutoff_7d)
        .execute()
    )
    calls_this_week = calls_week_resp.count or 0

    # Offer pipeline
    offer_resp = client.table("offers").select("offer_status, offer_amount").execute()
    offer_by_status: dict[str, int] = {}
    offer_pipeline_value = 0
    for o in (offer_resp.data or []):
        s = o.get("offer_status", "draft")
        offer_by_status[s] = offer_by_status.get(s, 0) + 1
        if s in ("sent", "countered", "accepted"):
            offer_pipeline_value += o.get("offer_amount") or 0

    # Conversion: active → appointment
    active = sum(workflow_pipeline.get(s, 0) for s in ("active_contact", "followup_required"))
    appt = workflow_pipeline.get("appointment_pending", 0) + workflow_pipeline.get("appointment_confirmed", 0)
    conversion_rate = round(appt / max(1, active + appt) * 100, 1)

    total_active = sum(
        v for k, v in workflow_pipeline.items()
        if k not in ("dead_lead", "closed")
    )

    return {
        "workflow_pipeline": workflow_pipeline,
        "stage_pipeline": stage_pipeline,
        "disposition_30d": disposition_counts,
        "hot_leads": hot_count,
        "followup_queue": followup_by_priority,
        "calls_this_week": calls_this_week,
        "offer_pipeline": offer_by_status,
        "offer_pipeline_value_cents": offer_pipeline_value,
        "active_leads": total_active,
        "conversion_rate_pct": conversion_rate,
        "total_closed": workflow_pipeline.get("closed", 0),
    }

import hashlib as _hashlib


def _idem_key(*parts) -> str:
    return _hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def load_intel_packet(lead_id: str) -> dict | None:
    client = _get_client()
    try:
        resp = client.table("intel_packets").select("*").eq("lead_id", lead_id).limit(1).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning("load_intel_packet failed lead_id={} error={}", lead_id, str(e))
        return None


def save_intel_packet(packet: dict) -> None:
    from datetime import datetime, timezone
    client = _get_client()
    lead_id = packet.get("lead_id")
    if not lead_id:
        return
    packet["updated_at"] = datetime.now(timezone.utc).isoformat()
    existing = load_intel_packet(lead_id)
    if existing:
        packet["packet_version"] = (existing.get("packet_version") or 1) + 1
        client.table("intel_packets").update(packet).eq("lead_id", lead_id).execute()
    else:
        client.table("intel_packets").insert(packet).execute()
    logger.debug("save_intel_packet lead_id={} version={}", lead_id, packet.get("packet_version"))


def write_packet_event(
    lead_id: str,
    call_sid: str,
    event_type: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
    changed_fields: list | None = None,
    triggered_by: str = "system",
) -> None:
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid, event_type, str(changed_fields))
    try:
        client.table("packet_events").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "event_type": event_type,
            "before_state": before_state,
            "after_state": after_state,
            "changed_fields": changed_fields or [],
            "triggered_by": triggered_by,
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_packet_event failed error={}", str(e))


def write_tool_gate_log(
    lead_id: str | None,
    call_sid: str | None,
    tool_name: str,
    permission_level: str,
    gate_result: str,
    gate_reason: str = "",
    packet_version: int = 0,
) -> None:
    client = _get_client()
    ikey = _idem_key(lead_id or "", call_sid or "", tool_name, gate_result, gate_reason)
    try:
        client.table("tool_gate_log").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "tool_name": tool_name,
            "permission_level": permission_level,
            "gate_result": gate_result,
            "gate_reason": gate_reason,
            "packet_version": packet_version,
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_tool_gate_log failed error={}", str(e))


def create_approval_request(
    lead_id: str,
    call_sid: str,
    approval_type: str,
    requested_action: str,
    risk_reason: str = "",
    context_snapshot: dict | None = None,
    expires_minutes: int = 2,
    priority: str = "high",
) -> str:
    from datetime import datetime, timezone, timedelta
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid, approval_type, requested_action)
    approval_id = ikey
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)).isoformat()
    try:
        client.table("approval_requests").insert({
            "id": approval_id,
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "approval_type": approval_type,
            "requested_action": requested_action,
            "risk_reason": risk_reason,
            "context_snapshot": context_snapshot or {},
            "expires_at": expires_at,
            "priority": priority,
            "expires_reason": "call_timeout",
        }).execute()
        logger.info("approval_request created id={} action={}", approval_id, requested_action)
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("create_approval_request failed error={}", str(e))
    return approval_id


def get_pending_approval(lead_id: str, call_sid: str) -> dict | None:
    from datetime import datetime, timezone
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = (
            client.table("approval_requests")
            .select("*")
            .eq("lead_id", lead_id)
            .eq("call_sid", call_sid)
            .eq("status", "pending")
            .gt("expires_at", now)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning("get_pending_approval failed error={}", str(e))
        return None


def resolve_approval_request(
    approval_id: str,
    approved_by: str,
    status: str,
    answer: str = "",
) -> None:
    from datetime import datetime, timezone
    client = _get_client()
    try:
        client.table("approval_requests").update({
            "status": status,
            "approved_by": approved_by,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "context_snapshot": {"answer": answer},
        }).eq("id", approval_id).execute()
    except Exception as e:
        logger.warning("resolve_approval_request failed id={} error={}", approval_id, str(e))


def write_bob_feedback_event(
    lead_id: str,
    call_sid: str | None,
    event_type: str,
    payload: dict,
) -> None:
    from datetime import datetime, timezone
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid or "", event_type, str(sorted(payload.items())))
    try:
        client.table("bob_feedback_events").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "event_type": event_type,
            "payload": payload,
        }).execute()
        logger.debug("bob_feedback_event written lead_id={} type={}", lead_id, event_type)
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_bob_feedback_event failed error={}", str(e))


import hashlib as _hashlib


def _idem_key(*parts) -> str:
    return _hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def load_intel_packet(lead_id: str) -> dict | None:
    client = _get_client()
    try:
        resp = client.table("intel_packets").select("*").eq("lead_id", lead_id).limit(1).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning("load_intel_packet failed lead_id={} error={}", lead_id, str(e))
        return None


def save_intel_packet(packet: dict) -> None:
    from datetime import datetime, timezone
    client = _get_client()
    lead_id = packet.get("lead_id")
    if not lead_id:
        return
    packet["updated_at"] = datetime.now(timezone.utc).isoformat()
    existing = load_intel_packet(lead_id)
    if existing:
        packet["packet_version"] = (existing.get("packet_version") or 1) + 1
        client.table("intel_packets").update(packet).eq("lead_id", lead_id).execute()
    else:
        client.table("intel_packets").insert(packet).execute()


def write_packet_event(lead_id, call_sid, event_type, before_state=None, after_state=None, changed_fields=None, triggered_by="system"):
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid or "", event_type, str(changed_fields))
    try:
        client.table("packet_events").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "event_type": event_type,
            "before_state": before_state,
            "after_state": after_state,
            "changed_fields": changed_fields or [],
            "triggered_by": triggered_by,
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_packet_event failed error={}", str(e))


def write_tool_gate_log(lead_id, call_sid, tool_name, permission_level, gate_result, gate_reason="", packet_version=0):
    client = _get_client()
    ikey = _idem_key(lead_id or "", call_sid or "", tool_name, gate_result, gate_reason)
    try:
        client.table("tool_gate_log").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "tool_name": tool_name,
            "permission_level": permission_level,
            "gate_result": gate_result,
            "gate_reason": gate_reason,
            "packet_version": packet_version,
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_tool_gate_log failed error={}", str(e))


def create_approval_request(lead_id, call_sid, approval_type, requested_action, risk_reason="", context_snapshot=None, expires_minutes=2, priority="high") -> str:
    from datetime import datetime, timezone, timedelta
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid or "", approval_type, requested_action)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)).isoformat()
    try:
        client.table("approval_requests").insert({
            "id": ikey,
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "approval_type": approval_type,
            "requested_action": requested_action,
            "risk_reason": risk_reason,
            "context_snapshot": context_snapshot or {},
            "expires_at": expires_at,
            "priority": priority,
            "expires_reason": "call_timeout",
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("create_approval_request failed error={}", str(e))
    return ikey


def get_pending_approval(lead_id: str, call_sid: str) -> dict | None:
    from datetime import datetime, timezone
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = (
            client.table("approval_requests")
            .select("*")
            .eq("lead_id", lead_id)
            .eq("call_sid", call_sid)
            .eq("status", "pending")
            .gt("expires_at", now)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.warning("get_pending_approval failed error={}", str(e))
        return None


def resolve_approval_request(approval_id, approved_by, status, answer=""):
    from datetime import datetime, timezone
    client = _get_client()
    try:
        client.table("approval_requests").update({
            "status": status,
            "approved_by": approved_by,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "context_snapshot": {"answer": answer},
        }).eq("id", approval_id).execute()
    except Exception as e:
        logger.warning("resolve_approval_request failed id={} error={}", approval_id, str(e))


def write_bob_feedback_event(lead_id, call_sid, event_type, payload):
    client = _get_client()
    ikey = _idem_key(lead_id, call_sid or "", event_type, str(sorted((payload or {}).items())))
    try:
        client.table("bob_feedback_events").insert({
            "lead_id": lead_id,
            "call_sid": call_sid,
            "idempotency_key": ikey,
            "event_type": event_type,
            "payload": payload or {},
        }).execute()
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("write_bob_feedback_event failed error={}", str(e))
