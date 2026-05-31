from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta

import pytz
from loguru import logger

_PACIFIC = pytz.timezone("America/Los_Angeles")
_MAX_ACTIONS_PER_RUN = 15
_WARM_SILENCE_DAYS = 7
_COLD_SILENCE_DAYS = 14
_MAX_NO_ANSWER_ATTEMPTS = 3


def _is_calling_hours() -> bool:
    now = datetime.now(_PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 9))
    end = int(os.environ.get("CALLING_HOURS_END", 20))
    return start <= now.hour < end


def _days_since(iso: str | None) -> float:
    if not iso:
        return 9999
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 9999


def _decide_channel(lead: dict) -> str | None:
    disposition = (lead.get("disposition") or "").upper()
    last_contact = lead.get("last_called_at") or lead.get("last_sms_at")
    days_silent = _days_since(last_contact)
    call_attempts = lead.get("call_attempts") or 0
    drip_started = lead.get("drip_started_at")
    owner_email = lead.get("owner_email")
    email_drip_started = lead.get("email_drip_started_at")
    callable_flag = lead.get("callable")
    opted_out = lead.get("opted_out") or False
    dnc = lead.get("dnc_blocked") or False

    if opted_out or dnc:
        return None

    if not last_contact:
        if callable_flag and _is_calling_hours():
            return "call"
        if lead.get("owner_phone"):
            return "sms"
        return None

    if disposition == "HOT":
        if days_silent >= 1 and _is_calling_hours() and callable_flag:
            return "call"
        if days_silent >= 1:
            return "sms"

    if disposition in ("WARM", ""):
        if days_silent >= _WARM_SILENCE_DAYS:
            if call_attempts < _MAX_NO_ANSWER_ATTEMPTS and _is_calling_hours() and callable_flag:
                return "call"
            return "sms"

    if disposition == "COLD":
        if days_silent >= _COLD_SILENCE_DAYS:
            if not drip_started:
                return "restart_drip"
            return "sms"

    if owner_email and not email_drip_started and days_silent >= 3:
        return "email_drip"

    return None


def _generate_personalized_sms(lead: dict, prop: dict) -> str:
    import anthropic
    first_name = (lead.get("owner_first_name") or (lead.get("owner_name") or "").split()[0] or "").strip() or "there"
    motivation = lead.get("motivation_level")
    distress = (prop.get("distress_type") or "general").replace("_", " ")
    call_summary = (lead.get("call_summary") or "")[:120]
    hot_topics = (lead.get("hot_topics") or "")[:80]
    price_floor = lead.get("price_floor")
    next_action = (lead.get("next_best_action") or "")[:80]
    city = prop.get("city", "")
    address = prop.get("address", "your property")

    context_parts = [f"Situation: {distress}"]
    if motivation:
        context_parts.append(f"Motivation: {motivation}/10")
    if call_summary:
        context_parts.append(f"Last call: {call_summary}")
    if hot_topics:
        context_parts.append(f"Key concerns: {hot_topics}")
    if price_floor:
        context_parts.append(f"Price they mentioned: ${int(price_floor):,}")
    if next_action:
        context_parts.append(f"Best next step: {next_action}")

    system = (
        "You write short personal outreach SMS messages for a local cash home buyer "
        "in San Joaquin County CA. Under 155 chars. Sound human and specific. "
        "Reference their real situation. Soft call to action. No exclamation marks. "
        "Never sound like a mass text. Return ONLY the message text."
    )
    user = (
        f"Write an SMS to {first_name} about {address}{(' in ' + city) if city else ''}.\n"
        + "\n".join(context_parts)
    )

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        msg = resp.content[0].text.strip().strip('"').strip("'")
        if len(msg) > 155:
            msg = msg[:152] + "..."
        return msg
    except Exception as e:
        logger.warning("sophia_loop llm_sms failed error={}", str(e))
        return f"Hey {first_name} — still thinking about your property on {address}. Any updates on your end? - Sophia SJ House Buyers"


def run_sophia_loop() -> dict:
    from backend.lib.db import _get_client, start_lead_drip, start_email_drip_for_lead
    from backend.alerts.sms import send_sms
    from backend.alerts.drip import get_sequence_name
    from backend.voice.outbound import call_lead

    logger.info("sophia_loop starting")
    client = _get_client()
    now = datetime.now(timezone.utc)

    resp = (
        client.table("leads")
        .select("*, properties(*)")
        .eq("opted_out", False)
        .eq("dnc_blocked", False)
        .neq("stage", "dead")
        .neq("stage", "walkthrough_booked")
        .limit(60)
        .execute()
    )

    leads = resp.data or []
    leads.sort(key=lambda l: l.get("composite_score") or 0, reverse=True)

    actions = 0
    results = {"called": 0, "sms": 0, "drip_started": 0, "email_drip": 0, "skipped": 0}

    for lead in leads:
        if actions >= _MAX_ACTIONS_PER_RUN:
            break

        prop = lead.get("properties") or {}
        channel = _decide_channel(lead)

        if channel is None:
            results["skipped"] += 1
            continue

        lead_id = lead["id"]

        try:
            if channel == "call":
                result = call_lead(lead_id, bypass_cooldown=False)
                if result.get("success"):
                    results["called"] += 1
                    actions += 1

            elif channel == "sms":
                phone = lead.get("owner_phone")
                if not phone:
                    results["skipped"] += 1
                    continue
                body = _generate_personalized_sms(lead, prop)
                sent = send_sms(to=phone, body=body, lead_id=lead_id)
                if sent:
                    results["sms"] += 1
                    actions += 1

            elif channel == "restart_drip":
                phone = lead.get("owner_phone")
                if not phone:
                    results["skipped"] += 1
                    continue
                sequence = get_sequence_name(prop.get("distress_type"))
                start_lead_drip(lead_id, sequence, now.isoformat(), initial_day=-1)
                results["drip_started"] += 1
                actions += 1

            elif channel == "email_drip":
                email = lead.get("owner_email")
                if not email:
                    results["skipped"] += 1
                    continue
                start_email_drip_for_lead(lead_id, now.isoformat())
                results["email_drip"] += 1
                actions += 1

        except Exception as e:
            logger.warning("sophia_loop failed lead_id={} channel={} error={}", lead_id, channel, str(e))
            results["skipped"] += 1

    logger.info("sophia_loop complete actions={} results={}", actions, results)
    return results
