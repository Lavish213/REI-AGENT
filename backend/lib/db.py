import os
from datetime import datetime, timedelta, timezone

from loguru import logger
from supabase import create_client, Client, ClientOptions

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key, options=ClientOptions(postgrest_client_timeout=10))
        logger.info("Supabase client initialized")
    return _client


def get_supabase() -> Client:
    return _get_client()


def upsert_property(data: dict) -> str:
    client = _get_client()
    payload = {key: value for key, value in data.items() if not key.startswith("_")}
    response = client.table("properties").upsert(payload, on_conflict="apn").execute()
    if not response.data or not response.data[0].get("id"):
        raise RuntimeError("Property was not saved")
    data["id"] = response.data[0]["id"]
    return data["id"]


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
    client.table("properties").update({"lead_id": lead_id}).eq("id", property_id).execute()
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
    response = client.table("leads").update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", lead_id).execute()
    if not response.data:
        raise ValueError("Lead stage update was not confirmed")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        .select("*, properties!properties_lead_id_fkey(*)")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    )
    result = response.data[0] if response.data else None
    if result and isinstance(result.get("properties"), list):
        result["properties"] = result["properties"][0] if result["properties"] else {}
    logger.debug("get_lead_with_property id={} found={}", lead_id, result is not None)
    return result


def update_lead_call_outcome(lead_id: str, outcome: str, call_sid: str, duration: int = 0) -> None:
    if not call_sid:
        raise ValueError("Provider call ID is required")
    _get_client().rpc("record_provider_call_outcome", {
        "p_lead_id": lead_id,
        "p_call_sid": call_sid,
        "p_outcome": outcome,
        "p_duration": max(0, duration),
    }).execute()


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
        .select("*, properties!properties_lead_id_fkey(*)")
        .eq("stage", "walkthrough_booked")
        .not_.is_("appointment_at", "null")
        .execute()
    )
    appointments = client.table("voice_appointments").select("lead_id,starts_at").eq("status", "confirmed").execute().data or []
    def timestamp(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (AttributeError, TypeError, ValueError):
            return None
    confirmed = {(row["lead_id"], timestamp(row["starts_at"])) for row in appointments}
    return [row for row in response.data or [] if timestamp(row.get("appointment_at")) is not None and (row["id"], timestamp(row["appointment_at"])) in confirmed and not row.get("opted_out")]


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
        .select("*, properties!properties_lead_id_fkey(*)")
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
        "objections": "objections",
        "next_step": "next_step",
        "followup_priority": "followup_priority",
        "extraction_confidence": "extraction_confidence",
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
        mao_calculated = (arv_used * 70 // 100) - repair_estimate

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
        response = client.table("approval_requests").insert({
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
        if not response.data:
            raise RuntimeError("Approval request persistence was not confirmed")
    except Exception as e:
        if "duplicate" not in str(e).lower() and "unique" not in str(e).lower():
            logger.warning("create_approval_request failed error={}", str(e))
            raise
        response = client.table("approval_requests").select("id").eq("id", ikey).eq("status", "pending").gt("expires_at", datetime.now(timezone.utc).isoformat()).execute()
        if not response.data:
            raise ValueError("No current pending approval request exists") from e
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
    if status not in {"approved", "rejected"}:
        raise ValueError("An explicit approved or rejected decision is required")
    now = datetime.now(timezone.utc).isoformat()
    response = _get_client().table("approval_requests").update({
        "status": status,
        "approved_by": approved_by,
        "resolved_at": now,
        "context_snapshot": {"answer": answer},
    }).eq("id", approval_id).eq("status", "pending").gt("expires_at", now).execute()
    if not response.data:
        raise ValueError("Approval is missing, expired, or already resolved")
    return response.data[0]


def create_operator_query(lead_id, question, context):
    from uuid import uuid4
    query_id = "op_" + uuid4().hex
    response = _get_client().table("operator_queries").insert({"id": query_id, "lead_id": lead_id or None, "question": question, "context": context, "status": "pending"}).execute()
    if not response.data:
        raise RuntimeError("Operator request persistence was not confirmed")
    return query_id


def get_operator_answer(query_id):
    response = _get_client().table("operator_queries").select("status,answer").eq("id", query_id).limit(1).execute()
    row = response.data[0] if response.data else {}
    return row.get("answer") if row.get("status") == "answered" else None


def close_operator_query(query_id):
    _get_client().table("operator_queries").update({"status": "closed"}).eq("id", query_id).eq("status", "answered").execute()


def record_operator_reply(body):
    from datetime import datetime, timezone, timedelta
    import re
    match = re.fullmatch(r"(op_[0-9a-f]{32})\s+(.+)", body.strip(), re.DOTALL)
    if not match:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    response = _get_client().table("operator_queries").update({"answer": match.group(2).strip(), "status": "answered"}).eq("id", match.group(1)).eq("status", "pending").gt("created_at", cutoff).execute()
    return bool(response.data)


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


def reserve_voice_appointment(lead_id: str, starts_at: str, address: str) -> str:
    response = _get_client().rpc("reserve_voice_appointment", {
        "p_lead_id": lead_id,
        "p_starts_at": starts_at,
        "p_address": address,
    }).execute()
    if not response.data:
        raise RuntimeError("Appointment reservation was not confirmed")
    return str(response.data)


def save_callback(lead_id: str, callback_at: str, notes: str) -> None:
    response = _get_client().table("leads").update({
        "callback_scheduled_at": callback_at,
        "callback_notes": notes,
    }).eq("id", lead_id).execute()
    if not response.data:
        raise RuntimeError("Callback was not saved")


def get_operator_user(access_token: str):
    response = _get_client().auth.get_user(access_token)
    user = response.user
    if user and (user.app_metadata or {}).get("role") in ("operator", "admin"):
        return user
    return None


def record_do_not_call(lead_id: str, phone: str) -> None:
    client = _get_client()
    if phone:
        client.table("dnc_list").upsert({"phone": phone}, on_conflict="phone").execute()
    if lead_id:
        mark_lead_opted_out(lead_id)


def phone_is_do_not_call(phone: str) -> bool:
    phone = _suppression_phone(phone)
    if local_phone_suppressed(phone):
        return True
    response = _get_client().table("dnc_list").select("id").eq("phone", phone).limit(1).execute()
    return bool(response.data)


def claim_due_callbacks(limit: int = 3) -> list[dict]:
    return _get_client().rpc("claim_due_callbacks", {"p_limit": limit}).execute().data or []


def claim_due_call_followups(limit: int = 5) -> list[dict]:
    return _get_client().rpc("claim_due_call_followups", {"p_limit": limit}).execute().data or []


def finish_callback_claim(lead_id: str, scheduled_at: str, success: bool, claim_token: str | None = None) -> None:
    if not claim_token:
        raise ValueError("Callback claim ownership is required")
    changes = {"callback_claimed_until": None, "callback_claim_token": None}
    if success:
        changes["callback_scheduled_at"] = None
    _get_client().table("leads").update(changes).eq("id", lead_id).eq("callback_scheduled_at", scheduled_at).eq("callback_claim_token", claim_token).execute()


def finish_followup_claim(followup_id: str, success: bool, claim_token: str | None = None) -> None:
    if not claim_token:
        raise ValueError("Follow-up claim ownership is required")
    _get_client().table("followups").update({
        "state": "completed" if success else "pending",
        "claimed_until": None,
        "claim_token": None,
    }).eq("id", followup_id).eq("state", "processing").eq("claim_token", claim_token).execute()


def warm_database() -> None:
    _get_client().table("leads").select("id").limit(1).execute()


def save_recording_metadata(call_sid: str, recording_url: str, recording_sid: str, duration: int) -> None:
    if not call_sid or not recording_url:
        raise ValueError("Recording requires a provider call ID and URL")
    _get_client().table("calls").update({
        "recording_url": recording_url,
        "recording_sid": recording_sid,
        "recording_duration_seconds": max(0, duration),
    }).eq("signalwire_call_id", call_sid).execute()


def save_call_grade(call_sid: str, values: dict) -> None:
    _get_client().table("calls").update(values).eq("signalwire_call_id", call_sid).execute()


def campaign_is_running(campaign_id: str = "default") -> bool:
    response = _get_client().table("campaigns").select("state").eq("id", campaign_id).limit(1).execute()
    return bool(response.data and response.data[0].get("state") == "running")


def list_walkthrough_availability() -> list[dict]:
    client = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    slots = client.table("walkthrough_availability").select("*").gt("starts_at", now).order("starts_at").limit(100).execute().data or []
    appointments = client.table("voice_appointments").select("starts_at,ends_at").eq("status", "confirmed").gt("ends_at", now).execute().data or []
    def parsed(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return [slot for slot in slots if not any(parsed(slot["starts_at"]) < parsed(appointment["ends_at"]) and parsed(slot["ends_at"]) > parsed(appointment["starts_at"]) for appointment in appointments)]


def add_walkthrough_availability(starts_at: str, ends_at: str) -> None:
    _get_client().table("walkthrough_availability").upsert({"starts_at": starts_at, "ends_at": ends_at}, on_conflict="starts_at").execute()


def update_sms_contact_time(lead_id: str, sent_at: str) -> None:
    _get_client().table("leads").update({"last_sms_at": sent_at}).eq("id", lead_id).execute()


def record_suppression_event(
    tenant_id: str,
    lead_id: str | None,
    contact_point: str,
    method: str,
    source: str,
    contact_type: str = "phone",
    channel: str = "all",
    reason: str | None = None,
    call_sid: str | None = None,
    verbatim: str | None = None,
    actor: str = "system",
) -> str | None:
    client = _get_client()
    row = {
        "tenant_id": tenant_id,
        "lead_id": lead_id or None,
        "contact_point": contact_point,
        "contact_type": contact_type,
        "channel": channel,
        "action": "suppressed",
        "reason": reason,
        "method": method,
        "source": source,
        "call_sid": call_sid,
        "verbatim": (verbatim or "")[:2000] or None,
        "actor": actor,
    }
    result = client.table("suppression_events").insert(row).execute()
    event_id = result.data[0]["id"] if result.data else None
    logger.info(
        "suppression_recorded event_id={} lead_id={} method={} channel={}",
        event_id, lead_id, method, channel,
    )
    return event_id


def add_to_dnc(tenant_id: str, phone: str, reason: str = "seller_request") -> None:
    client = _get_client()
    client.table("dnc_list").upsert(
        {"tenant_id": tenant_id, "phone": phone, "reason": reason},
        on_conflict="phone",
    ).execute()
    logger.info("dnc_added phone_suffix={} reason={}", phone[-4:], reason)


def is_contact_suppressed(tenant_id: str, contact_point: str) -> bool:
    client = _get_client()
    result = (
        client.table("suppression_events")
        .select("action")
        .eq("tenant_id", tenant_id)
        .eq("contact_point", contact_point)
        .order("occurred_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return False
    return result.data[0].get("action") == "suppressed"


def try_write(label: str, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return True
    except Exception as error:
        logger.exception("write_failed op={} error={}", label, str(error))
        return False


def record_bob_call_facts(lead_id, call_sid, facts):
    import os
    if not lead_id or not call_sid or not isinstance(facts, dict) or not facts:
        return False
    response = _get_client().rpc("bob_record_call_facts", {
        "p_tenant_id": os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001"),
        "p_lead_id": lead_id, "p_call_sid": call_sid, "p_facts": facts,
    }).execute()
    if response.data is not True:
        raise RuntimeError("Bob call facts were not persisted")
    return True


def _bob_fact_outbox():
    from pathlib import Path
    path = Path(os.environ.get("VOICE_FACT_OUTBOX_PATH", "/data/sophia/bob-facts.sqlite3"))
    return _private_journal_connection(path, ("CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, lead_id TEXT NOT NULL, call_sid TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, leased_until REAL, state TEXT NOT NULL DEFAULT 'pending', error TEXT)",))


def stage_bob_call_facts(lead_id, call_sid, facts):
    import json
    import time
    from uuid import UUID, uuid5, NAMESPACE_URL
    if not lead_id or not call_sid or not isinstance(facts, dict) or not facts:
        return None
    UUID(lead_id)
    tenant = os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")
    UUID(tenant)
    if not isinstance(call_sid, str) or not 1 <= len(call_sid) <= 200:
        raise ValueError("Invalid call binding")
    if len(facts) > 7:
        raise ValueError("Too many checklist facts")
    now = datetime.now(timezone.utc)
    for box, fact in facts.items():
        if box not in {"right_person", "property_confirmed", "occupancy", "condition", "timeline", "motivation", "next_step"} or not isinstance(fact, dict) or type(fact.get("confirmed")) is not bool or fact.get("source") != "transcript_verified" or fact.get("call_sid") != call_sid:
            raise ValueError("Invalid fact provenance")
        observed = datetime.fromisoformat(fact["verified_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or not -60 <= (now - observed).total_seconds() <= 86400:
            raise ValueError("Invalid fact timestamp")
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload) > 8192:
        raise ValueError("Fact payload too large")
    event_id = str(uuid5(NAMESPACE_URL, tenant + ":" + lead_id + ":" + call_sid + ":" + payload))
    connection = _bob_fact_outbox()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM facts WHERE id=?", (event_id,)).fetchone():
                return event_id
            if connection.execute("SELECT count(*) FROM facts").fetchone()[0] >= 10000:
                raise RuntimeError("Fact journal full; operator recovery required")
            connection.execute("INSERT INTO facts(id,tenant_id,lead_id,call_sid,payload,created,due) VALUES(?,?,?,?,?,?,?)", (event_id, tenant, lead_id, call_sid, payload, time.time(), time.time()))
    finally:
        connection.close()
    return event_id


def flush_bob_call_fact_outbox(limit=20):
    import json
    import time
    from uuid import uuid4
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid fact flush limit")
    result = {"delivered": 0, "failed": 0, "expired": 0}
    tenant = os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")
    for _ in range(limit):
        connection = _bob_fact_outbox()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT id,lead_id,call_sid,payload,attempts FROM facts WHERE tenant_id=? AND state='pending' AND due<=? AND (leased_until IS NULL OR leased_until<=?) ORDER BY created,id LIMIT 1", (tenant, time.time(), time.time())).fetchone()
                if row is None:
                    break
                event_id, lead_id, call_sid, payload, attempts = row
                lease = str(uuid4())
                connection.execute("UPDATE facts SET lease=?,leased_until=?,attempts=attempts+1 WHERE id=?", (lease, time.time()+120, event_id))
            facts = json.loads(payload)
            expired = any((datetime.now(timezone.utc)-datetime.fromisoformat(fact["verified_at"].replace("Z", "+00:00"))).total_seconds() > 86400 for fact in facts.values())
            try:
                if expired:
                    raise ValueError("fact_expired_before_delivery")
                response = _get_client().rpc("bob_accept_call_facts", {"p_tenant_id": tenant, "p_lead_id": lead_id, "p_call_sid": call_sid, "p_event_id": event_id, "p_facts": facts}).execute()
                if response.data is not True:
                    raise RuntimeError("fact_receipt_not_confirmed")
            except Exception as error:
                with connection:
                    connection.execute("UPDATE facts SET state=?,due=?,lease=NULL,leased_until=NULL,error=? WHERE id=? AND lease=?", ("dead" if expired else "pending", time.time()+min(300, 2**min(attempts+1,8)), type(error).__name__, event_id, lease))
                result["expired" if expired else "failed"] += 1
                logger.warning("bob_fact_delivery_failed event_id={} type={}", event_id, type(error).__name__)
            else:
                with connection:
                    deleted = connection.execute("DELETE FROM facts WHERE id=? AND lease=?", (event_id, lease)).rowcount
                if deleted:
                    result["delivered"] += 1
        finally:
            connection.close()
    return result


def bob_fact_journal_health():
    import time
    connection = _bob_fact_outbox()
    try:
        tenant = os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")
        rows = connection.execute("SELECT state,count(*),min(created) FROM facts WHERE tenant_id=? GROUP BY state", (tenant,)).fetchall()
        result = {"pending": 0, "dead": 0, "oldest_pending_seconds": 0}
        for state, count, created in rows:
            result[state] = count
            if state == "pending":
                result["oldest_pending_seconds"] = max(0, time.time()-created)
        return result
    finally:
        connection.close()


def bob_integration_health():
    response = _get_client().rpc("bob_integration_health", {"p_tenant_id": os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")}).execute()
    if not isinstance(response.data, dict) or response.data.get("contract_version") != "2.1" or response.data.get("backend") != "REI-AGENT":
        raise RuntimeError("Bob schema contract missing or incompatible")
    return response.data


def accept_bob_brief_event(event_id, payload):
    response = _get_client().rpc("bob_accept_brief_event", {"p_tenant_id": os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001"), "p_event_id": event_id, "p_payload": payload}).execute()
    return response.data is True


def _dashboard_event_outbox():
    from pathlib import Path
    configured = os.environ.get("KARPATHYS_OUTBOX_PATH", "")
    if not configured:
        raise RuntimeError("Dashboard event journal requires an absolute non-symlink persistent path")
    return _private_journal_connection(Path(configured), (
        "CREATE TABLE IF NOT EXISTS dashboard_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, target TEXT NOT NULL, call_sid TEXT NOT NULL, endpoint TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL, due REAL NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, leased_until REAL, state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','delivered','dead')), error TEXT, receipt TEXT, delivered_at REAL)",
        "CREATE INDEX IF NOT EXISTS dashboard_events_due ON dashboard_events(state,due,leased_until)",
        "CREATE INDEX IF NOT EXISTS dashboard_events_call ON dashboard_events(target,call_sid,seq)",
    ))


def stage_dashboard_event(endpoint, payload, target):
    import hashlib
    import json
    import time
    from uuid import uuid5, NAMESPACE_URL
    allowed = {"call", "turn", "complete", "ended", "transcript", "failed", "business", "sophia/disposition-action"}
    if endpoint not in allowed or not isinstance(payload, dict) or not isinstance(target, str) or len(target) != 64:
        raise ValueError("Invalid dashboard event")
    sid = payload.get("call_sid")
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 255:
        raise ValueError("Dashboard event requires a provider call identity")
    suffix = ""
    if endpoint == "turn":
        if payload.get("speaker") not in {"user", "seller", "sophia", "assistant", "system"} or type(payload.get("turn_index")) is not int or not 0 <= payload["turn_index"] <= 10000:
            raise ValueError("Invalid dashboard turn identity")
        suffix = f":{payload['speaker']}:{payload['turn_index']}"
    if endpoint == "business":
        revision = payload.get("revision")
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Invalid business snapshot revision")
        suffix = ":" + revision
    stable = json.dumps({key: value for key, value in payload.items() if key != "occurred_at"}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    fingerprint = hashlib.sha256(stable.encode()).hexdigest()
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(serialized.encode()) > 1024 * 1024:
        raise ValueError("Dashboard event exceeds journal payload budget")
    event_id = str(uuid5(NAMESPACE_URL, target + ":" + sid + ":" + endpoint + suffix))
    now = time.time()
    connection = _dashboard_event_outbox()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT fingerprint FROM dashboard_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("Conflicting dashboard event replay")
                return event_id
            connection.execute("DELETE FROM dashboard_events WHERE state='delivered' AND delivered_at<?", (now - 7 * 86400,))
            count, size = connection.execute("SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM dashboard_events").fetchone()
            if count >= 100000 or size + len(serialized.encode()) > 64 * 1024 * 1024:
                raise RuntimeError("Dashboard event journal full; operator recovery required")
            connection.execute("INSERT INTO dashboard_events(event_id,target,call_sid,endpoint,fingerprint,payload,created,due,expires) VALUES(?,?,?,?,?,?,?,?,?)", (event_id, target, sid, endpoint, fingerprint, serialized, now, now, now + 7 * 86400))
        return event_id
    finally:
        connection.close()


def claim_dashboard_event(target):
    import json
    import time
    from uuid import uuid4
    now = time.time()
    connection = _dashboard_event_outbox()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE dashboard_events SET state='dead',error='delivery_expired',lease=NULL,leased_until=NULL WHERE state='pending' AND expires<=? AND (leased_until IS NULL OR leased_until<=?)", (now, now))
            connection.execute("UPDATE dashboard_events SET state='dead',error='destination_changed',lease=NULL,leased_until=NULL WHERE state='pending' AND target<>? AND (leased_until IS NULL OR leased_until<=?)", (target, now))
            connection.execute("UPDATE dashboard_events SET state='dead',error='call_creation_failed' WHERE state='pending' AND endpoint<>'call' AND (leased_until IS NULL OR leased_until<=?) AND EXISTS (SELECT 1 FROM dashboard_events root WHERE root.target=dashboard_events.target AND root.call_sid=dashboard_events.call_sid AND root.endpoint='call' AND root.state='dead')", (now,))
            row = connection.execute("SELECT e.* FROM dashboard_events e WHERE e.target=? AND e.state='pending' AND e.due<=? AND (e.leased_until IS NULL OR e.leased_until<=?) AND NOT EXISTS (SELECT 1 FROM dashboard_events active WHERE active.target=e.target AND active.call_sid=e.call_sid AND active.leased_until>? AND active.state='pending') AND (e.endpoint IN ('call','business') OR EXISTS (SELECT 1 FROM dashboard_events root WHERE root.target=e.target AND root.call_sid=e.call_sid AND root.endpoint='call' AND root.state='delivered')) AND (e.endpoint='call' OR NOT EXISTS (SELECT 1 FROM dashboard_events prior WHERE prior.target=e.target AND prior.call_sid=e.call_sid AND prior.endpoint<>'call' AND prior.state='pending' AND prior.seq<e.seq)) ORDER BY e.seq LIMIT 1", (target, now, now, now)).fetchone()
            if row is None:
                return None
            token = str(uuid4())
            connection.execute("UPDATE dashboard_events SET lease=?,leased_until=?,attempts=attempts+1 WHERE event_id=?", (token, now + 60, row["event_id"]))
            return {**dict(row), "lease": token, "attempts": row["attempts"] + 1, "payload": json.loads(row["payload"])}
    finally:
        connection.close()


def finish_dashboard_event(event_id, lease, receipt=None, error="transport_unavailable", permanent=False):
    import json
    import time
    now = time.time()
    connection = _dashboard_event_outbox()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM dashboard_events WHERE event_id=? AND state='pending' AND lease=? AND leased_until>?", (event_id, lease, now)).fetchone()
            if row is None:
                return False
            if receipt is not None:
                if not isinstance(receipt, dict) or receipt.get("persisted") is not True or type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != 1 or receipt.get("call_sid") != row["call_sid"] or not isinstance(receipt.get("receipt_id"), str) or not 1 <= len(receipt["receipt_id"]) <= 1024:
                    raise ValueError("Unconfirmed dashboard delivery receipt")
                safe_receipt = {key: receipt[key] for key in ("schema_version", "persisted", "receipt_id", "call_sid", "call_id", "session_id", "transcript_id", "turn_id") if key in receipt}
                serialized = json.dumps(safe_receipt, allow_nan=False)
                if len(serialized) > 8192:
                    raise ValueError("Invalid dashboard receipt budget")
                connection.execute("UPDATE dashboard_events SET state='delivered',receipt=?,payload='{}',error=NULL,delivered_at=?,lease=NULL,leased_until=NULL WHERE event_id=? AND lease=?", (serialized, now, event_id, lease))
            else:
                allowed_errors = {"transport_unavailable", "invalid_receipt", "authentication_rejected", "payload_rejected", "destination_changed", "worker_failed"}
                safe_error = error if error in allowed_errors else "worker_failed"
                delay = min(300, 2 ** min(row["attempts"], 8))
                connection.execute("UPDATE dashboard_events SET state=?,error=?,due=?,lease=NULL,leased_until=NULL WHERE event_id=? AND lease=?", ("dead" if permanent else "pending", safe_error, now + delay, event_id, lease))
            return True
    finally:
        connection.close()


def dashboard_event_journal_health():
    import time
    connection = _dashboard_event_outbox()
    try:
        result = {"pending": 0, "delivered": 0, "dead": 0, "leased": 0, "oldest_pending_seconds": 0, "errors": {}, "failed_events": []}
        for row in connection.execute("SELECT state,count(*) AS n,min(created) AS oldest FROM dashboard_events GROUP BY state"):
            result[row["state"]] = row["n"]
            if row["state"] == "pending":
                result["oldest_pending_seconds"] = max(0, time.time() - row["oldest"])
        result["leased"] = connection.execute("SELECT count(*) FROM dashboard_events WHERE state='pending' AND leased_until>?", (time.time(),)).fetchone()[0]
        result["errors"] = {row["error"]: row["n"] for row in connection.execute("SELECT error,count(*) AS n FROM dashboard_events WHERE state<>'delivered' AND error IS NOT NULL GROUP BY error")}
        result["failed_events"] = [dict(row) for row in connection.execute("SELECT event_id,endpoint,error,attempts FROM dashboard_events WHERE state='dead' ORDER BY seq DESC LIMIT 50")]
        return result
    finally:
        connection.close()


def retry_dashboard_event(event_id, target):
    import time
    from uuid import UUID
    UUID(event_id)
    now = time.time()
    connection = _dashboard_event_outbox()
    try:
        with connection:
            changed = connection.execute("UPDATE dashboard_events SET state='pending',error=NULL,due=?,expires=?,lease=NULL,leased_until=NULL WHERE event_id=? AND target=? AND state='dead'", (now, now + 7 * 86400, event_id, target)).rowcount
            return changed == 1
    finally:
        connection.close()



def _suppression_journal():
    from pathlib import Path
    configured = os.environ.get("CONTACT_SUPPRESSION_PATH", "")
    if not configured:
        raise RuntimeError("Contact suppression requires a persistent path")
    return _private_journal_connection(Path(configured), (
        "CREATE TABLE IF NOT EXISTS contact_suppression (phone TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, tenant_id TEXT NOT NULL, lead_id TEXT, method TEXT NOT NULL, call_sid TEXT, created REAL NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, leased_until REAL, recovered INTEGER NOT NULL DEFAULT 0)",
    ))


def _suppression_phone(phone):
    import re
    if not isinstance(phone, str) or len(phone) > 64:
        raise ValueError("Invalid suppression phone")
    if re.search(r"[^0-9+(). -]", phone):
        raise ValueError("Invalid suppression phone")
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = "1" + digits
    if not 8 <= len(digits) <= 15 or (len(digits) != 11 and not phone.strip().startswith("+")):
        raise ValueError("Invalid suppression phone")
    return "+" + digits


def stage_contact_suppression(tenant_id, phone, lead_id=None, method="seller_request", call_sid=None):
    import time
    from uuid import uuid4
    if not os.environ.get("CONTACT_SUPPRESSION_PATH"):
        return False
    phone = _suppression_phone(phone)
    if not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 128:
        raise ValueError("Suppression tenant is required")
    if not isinstance(method, str) or not method or len(method) > 128:
        raise ValueError("Invalid suppression method")
    connection = _suppression_journal()
    try:
        with connection:
            connection.execute("INSERT INTO contact_suppression(phone,event_id,tenant_id,lead_id,method,call_sid,created,due) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(phone) DO NOTHING", (phone, str(uuid4()), tenant_id, lead_id or None, method, call_sid, time.time(), time.time()))
        return True
    finally:
        connection.close()


def local_phone_suppressed(phone):
    if not os.environ.get("CONTACT_SUPPRESSION_PATH"):
        return False
    phone = _suppression_phone(phone)
    connection = _suppression_journal()
    try:
        return connection.execute("SELECT 1 FROM contact_suppression WHERE phone=?", (phone,)).fetchone() is not None
    finally:
        connection.close()


def suppression_journal_health():
    connection = _suppression_journal()
    try:
        row = connection.execute("SELECT count(*) AS total,coalesce(sum(recovered=0),0) AS pending FROM contact_suppression").fetchone()
        return dict(row)
    finally:
        connection.close()


def recover_contact_suppressions(limit=20):
    import time
    from uuid import uuid4
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid suppression recovery batch")
    tenant = os.environ.get("TENANT_ID") or "00000000-0000-0000-0000-000000000001"
    result = {"recovered": 0, "retrying": 0, "unowned": 0}
    for _ in range(limit):
        connection = _suppression_journal()
        try:
            now = time.time()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM contact_suppression WHERE tenant_id=? AND recovered=0 AND due<=? AND (leased_until IS NULL OR leased_until<=?) ORDER BY created LIMIT 1", (tenant, now, now)).fetchone()
            if row is None:
                connection.commit()
                break
            event = dict(row)
            lease = str(uuid4())
            connection.execute("UPDATE contact_suppression SET lease=?,leased_until=?,attempts=attempts+1 WHERE phone=?", (lease, now + 60, event["phone"]))
            connection.commit()
        finally:
            connection.close()
        saved = False
        try:
            client = _get_client()
            client.table("dnc_list").upsert({"tenant_id": event["tenant_id"], "phone": event["phone"], "reason": "seller_request"}, on_conflict="phone").execute()
            receipt = client.table("suppression_events").select("id,action,contact_point,tenant_id").eq("id", event["event_id"]).limit(1).execute()
            if not receipt.data:
                receipt = client.table("suppression_events").insert({"id": event["event_id"], "tenant_id": event["tenant_id"], "lead_id": event["lead_id"], "contact_point": event["phone"], "contact_type": "phone", "channel": "all", "action": "suppressed", "method": event["method"], "source": "durable_recovery", "call_sid": event["call_sid"], "actor": "system", "occurred_at": datetime.fromtimestamp(event["created"], timezone.utc).isoformat()}).execute()
            saved = any(item.get("id") == event["event_id"] and item.get("action") == "suppressed" and item.get("contact_point") == event["phone"] and item.get("tenant_id") == event["tenant_id"] for item in (receipt.data or []))
            dnc = client.table("dnc_list").select("phone").eq("phone", event["phone"]).limit(1).execute()
            saved = saved and any(item.get("phone") == event["phone"] for item in (dnc.data or []))
        except Exception as error:
            logger.warning("suppression_recovery_failed type={}", type(error).__name__)
        connection = _suppression_journal()
        try:
            with connection:
                changed = connection.execute("UPDATE contact_suppression SET recovered=?,due=?,lease=NULL,leased_until=NULL WHERE phone=? AND lease=? AND leased_until>?", (int(saved), time.time() + min(3600, 5 * 2 ** min(event["attempts"], 9)), event["phone"], lease, time.time())).rowcount
            result["unowned" if not changed else "recovered" if saved else "retrying"] += 1
        finally:
            connection.close()
    return result


def _private_journal_connection(path, statements):
    import fcntl
    import sqlite3
    import stat
    import time
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RuntimeError("Event journal requires an absolute non-symlink persistent path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
        raise RuntimeError("Event journal directory must be owned and private")
    lock = os.open(str(path) + ".init.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    connection = None
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Event journal initialization busy")
                time.sleep(0.01)
        if not path.exists():
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
        if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
            raise RuntimeError("Event journal must be a regular non-symlink file")
        os.chmod(path, 0o600)
        connection = sqlite3.connect(str(path), timeout=5)
        connection.row_factory = sqlite3.Row
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        for statement in statements:
            connection.execute(statement)
        connection.commit()
        return connection
    except BaseException:
        if connection is not None:
            connection.close()
        raise
    finally:
        os.close(lock)


def upsert_listing_candidate(data: dict):
    client = _get_client()
    existing = client.table("properties").select("id").eq("apn", data["apn"]).limit(1).execute()
    if existing.data:
        update = {key: data[key] for key in ("days_on_market", "last_list_price", "price_reduced")}
        client.table("properties").update(update).eq("id", existing.data[0]["id"]).execute()
        return existing.data[0]["id"]
    return upsert_property(data)


def persist_mls_candidate(candidate):
    import re
    apn = candidate.get("apn")
    if not isinstance(apn, str) or not re.fullmatch(r"[0-9]{8}", apn) or apn == "00000000" or candidate.get("county") != "San Joaquin" or candidate.get("state") != "CA" or not candidate.get("address"):
        return None
    payload = {key: candidate[key] for key in ("apn", "address", "city", "state", "county", "beds", "baths", "sqft", "year_built", "distress_type", "distress_score", "deal_viable", "last_list_price") if key in candidate}
    payload["days_on_market"] = candidate.get("days_on_market", 0)
    payload["price_reduced"] = candidate.get("distress_type") == "price_reduction"
    from uuid import UUID
    tenant = str(UUID(os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000001")))
    payload["tenant_id"] = tenant
    property_id = upsert_listing_candidate(payload)
    existing = get_lead_by_property(property_id)
    if existing:
        return existing['id']
    from uuid import uuid5, NAMESPACE_URL
    lead_id = str(uuid5(NAMESPACE_URL, tenant + ':mls:' + property_id))
    _get_client().table('leads').upsert({'id': lead_id, 'tenant_id': tenant, 'property_id': property_id, 'stage': 'new', 'callable': False}, on_conflict='id', ignore_duplicates=True).execute()
    saved = get_lead_by_property(property_id)
    if not saved:
        raise RuntimeError('MLS lead persistence was not confirmed')
    _get_client().table('properties').update({'lead_id': saved['id']}).eq('id', property_id).execute()
    return saved['id']


def dashboard_business_source(lead_id):
    lead = get_lead_with_property(lead_id)
    if not lead:
        raise ValueError("Missing canonical lead")
    return {"lead": lead, "offers": get_offers_for_lead(lead_id)[:20]}


def dashboard_lead_refresh_ids(offset=0):
    rows = _get_client().table("leads").select("id").order("id").range(offset, offset + 99).execute().data
    return [row['id'] for row in rows if row.get('id')]
