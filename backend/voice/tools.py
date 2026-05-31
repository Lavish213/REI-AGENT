import os
from datetime import datetime, timezone

import pytz
from loguru import logger

from backend.lib.db import (
    create_followup,
    insert_sms,
    update_lead_appointment,
    update_lead_stage,
)
from backend.alerts.sms import send_sms


_PACIFIC = pytz.timezone("America/Los_Angeles")


SOPHIA_TOOLS = [
    {
        "name": "book_appointment",
        "description": (
            "Book a property walkthrough appointment. "
            "Use only when seller explicitly agrees to a specific date and time. "
            "Confirm date and time before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Time in HH:MM 24hr format"},
                "address": {"type": "string", "description": "Property address"},
                "lead_id": {"type": "string", "description": "Lead ID"},
                "seller_phone": {"type": "string", "description": "Seller phone number"},
                "seller_name": {"type": "string", "description": "Seller first name"},
            },
            "required": ["date", "time", "address", "lead_id", "seller_phone"],
        },
    },
    {
        "name": "send_followup_sms",
        "description": (
            "Send a follow-up SMS to the seller. "
            "Use at the end of every call — whether appointment booked, callback scheduled, or just info sent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Seller phone number"},
                "message": {"type": "string", "description": "SMS under 160 characters"},
                "lead_id": {"type": "string", "description": "Lead ID"},
            },
            "required": ["to", "message", "lead_id"],
        },
    },
    {
        "name": "set_disposition",
        "description": (
            "Classify the lead once the call direction is clear. "
            "HOT: seller mentioned timeline, asked about price, agreed to appointment, or asked how the process works. "
            "WARM: engaged but not ready, open to callback. "
            "COLD: not interested now but not hostile, may reconsider. "
            "DEAD: hostile, wrong number, explicit no, or DNC request. "
            "Call once during the call when the picture is clear."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "disposition": {
                    "type": "string",
                    "enum": ["HOT", "WARM", "COLD", "DEAD"],
                    "description": "Lead classification",
                },
            },
            "required": ["disposition"],
        },
    },
    {
        "name": "schedule_followup",
        "description": (
            "Schedule a follow-up task for this lead. "
            "Use when seller asks to be called back, needs time to think, or next steps are agreed. "
            "priority: high=seller requested callback soon or HOT lead. medium=general callback. low=check-in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "Lead ID"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "Follow-up priority"},
                "notes": {"type": "string", "description": "Callback notes"},
                "callback_time": {"type": "string", "description": "Requested callback timing"},
            },
            "required": ["lead_id", "priority", "notes"],
        },
    },
    {
        "name": "end_call",
        "description": "End the conversation after wrapping up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "appointment_booked, not_interested, callback_scheduled, wrong_number, other",
                },
                "summary": {"type": "string", "description": "Short call summary"},
                "lead_id": {"type": "string", "description": "Lead ID"},
            },
            "required": ["reason", "summary", "lead_id"],
        },
    },
    {
        "name": "transfer_call",
        "description": (
            "Transfer this call to a human team member when the seller explicitly asks "
            "to speak with a real person, asks to speak with the owner, or when the "
            "situation requires human judgment such as legal questions or complex negotiations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why transfer is needed"},
                "lead_id": {"type": "string", "description": "Lead ID"},
            },
            "required": ["reason", "lead_id"],
        },
    },
    {
        "name": "schedule_callback",
        "description": "Schedule an auto-callback for this seller. Use when seller says call me back Tuesday or try me in an hour.",
        "input_schema": {
            "type": "object",
            "properties": {
                "delay_hours": {"type": "number"},
                "day_of_week": {"type": "string"},
                "notes": {"type": "string"},
                "lead_id": {"type": "string"},
            },
            "required": ["lead_id", "notes"],
        },
    },
    {
        "name": "ask_operator",
        "description": "Ask Angelo a question mid-call. Use for unusual pricing, legal questions, or anything outside your training. Call stays live up to 90s waiting for reply.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "context": {"type": "string"},
                "lead_id": {"type": "string"},
            },
            "required": ["question", "lead_id"],
        },
    },
    {
        "name": "send_followup_email",
        "description": "Send an email to the seller with offer summary. Use when seller gives their email or asks for something in writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Seller email address"},
                "first_name": {"type": "string"},
                "address": {"type": "string"},
                "offer_low": {"type": "integer"},
                "offer_high": {"type": "integer"},
                "lead_id": {"type": "string"},
            },
            "required": ["to", "lead_id"],
        },
    },
    {
        "name": "get_offer_range",
        "description": (
            "Get a live offer range for the property based on current comps. "
            "Use when seller asks what you would offer or what the property is worth. "
            "Requires address to be known."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Property address"},
                "lead_id": {"type": "string", "description": "Lead ID"},
            },
            "required": ["address", "lead_id"],
        },
    },
    {
        "name": "send_offer_summary",
        "description": "Send a cash offer summary via SMS to the seller. Use when seller asks what your offer would be or wants the number in writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seller_phone": {"type": "string", "description": "Seller phone number"},
                "offer_low": {"type": "integer", "description": "Low end of offer range in dollars"},
                "offer_high": {"type": "integer", "description": "High end of offer range in dollars"},
                "address": {"type": "string", "description": "Property address"},
                "lead_id": {"type": "string", "description": "Lead ID"},
            },
            "required": ["seller_phone", "lead_id"],
        },
    },
    {
        "name": "collect_and_send_email",
        "description": "Ask seller for their email then send offer summary. Use when seller asks for something in writing but no email is on file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Seller email address"},
                "address": {"type": "string", "description": "Property address"},
                "offer_low": {"type": "integer"},
                "offer_high": {"type": "integer"},
                "lead_id": {"type": "string"},
            },
            "required": ["lead_id"],
        },
    },
    {
        "name": "drop_voicemail",
        "description": "Leave a voicemail message when seller does not answer. Use only when call goes to voicemail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "script": {"type": "string", "description": "Voicemail script to use: standard, callback, or urgent"},
            },
            "required": ["lead_id"],
        },
    },
]



_RISKY_TOOLS_MAP = {
    "book_appointment":       "book_appointment",
    "send_offer_summary":     "send_summary",
    "send_followup_email":    "send_summary",
    "collect_and_send_email": "send_summary",
    "get_offer_range":        "quote_range",
    "drop_voicemail":         "send_summary",
}

_BLOCKED_RESPONSES = {
    "book_appointment":       "Let me have Alanzo confirm that appointment with you directly.",
    "send_offer_summary":     "I can walk you through what we're thinking, but let me have someone follow up in writing.",
    "send_followup_email":    "I can walk you through what we're thinking, but let me have someone follow up in writing.",
    "collect_and_send_email": "I can walk you through what we're thinking, but let me have someone follow up in writing.",
    "get_offer_range":        "I want to make sure we get you a real number. Let me have Alanzo follow up with the specifics.",
    "drop_voicemail":         "I'll have someone follow up with you.",
}

_ASK_ONLY_RESPONSES = {
    "book_appointment":       "I can discuss timing but let me have Alanzo confirm that walkthrough with you directly.",
    "send_offer_summary":     "Here's what we're thinking in rough terms — I'll have someone follow up in writing with specifics.",
    "get_offer_range":        "Based on what I'm seeing in the area, we'd be somewhere in a reasonable range — but let me have Alanzo give you a real number.",
}


def _preflight_gate(tool_name: str, tool_input: dict, call_ctx) -> dict:
    from backend.contracts.intel_packet import (
        ALWAYS_ALLOWED_TOOLS, GATED_TOOLS, get_permission_level, is_permission_expired
    )
    from backend.lib.db import write_tool_gate_log, create_approval_request

    lead_id = (tool_input.get("lead_id") or "") if tool_input else ""
    if not lead_id and call_ctx is not None:
        lead_id = getattr(call_ctx, "lead_id", "")
    call_sid = getattr(call_ctx, "_call_sid", "") if call_ctx else ""
    packet_version = getattr(call_ctx, "packet_version", 0) if call_ctx else 0

    if tool_name in ALWAYS_ALLOWED_TOOLS:
        return {"blocked": False, "level": "allowed"}

    if tool_name not in GATED_TOOLS:
        return {"blocked": False, "level": "allowed"}

    fallback_mode = getattr(call_ctx, "fallback_mode", False) if call_ctx else False
    if fallback_mode and tool_name in _RISKY_TOOLS_MAP:
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "fallback_blocked", "system_degraded", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "System unavailable right now.")}

    conflict_active = getattr(call_ctx, "conflict_active", False) if call_ctx else False
    if conflict_active and tool_name in _RISKY_TOOLS_MAP:
        approval_id = create_approval_request(
            lead_id=lead_id, call_sid=call_sid,
            approval_type="conflict_resolution", requested_action=tool_name,
            risk_reason="intel_conflict_detected", priority="high",
        )
        if call_ctx:
            call_ctx.approval_pending = approval_id
        write_tool_gate_log(lead_id, call_sid, tool_name, "ask_operator_required", "conflict_blocked", "conflict_active", packet_version)
        return {"blocked": True, "message": "Let me check with my team real quick — there's something I want to verify first."}

    intel_packet = getattr(call_ctx, "intel_packet", None) if call_ctx else None
    if not intel_packet:
        return {"blocked": False, "level": "open_default"}

    level = get_permission_level(intel_packet, tool_name)
    perms = intel_packet.get("action_permissions") or {}
    perm = perms.get(tool_name) or {}

    if is_permission_expired(perm):
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "permission_expired", "expires_at reached", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "Let me have someone follow up on that.")}

    if level == "blocked":
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "permission_blocked", perm.get("reason", ""), packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "Let me have someone follow up on that.")}

    if level == "ask_operator_required":
        write_tool_gate_log(lead_id, call_sid, tool_name, "ask_operator_required", "escalated_to_operator", "", packet_version)
        return {"blocked": True, "message": "Let me loop in my team on that — one second."}

    if level == "ask_only":
        write_tool_gate_log(lead_id, call_sid, tool_name, "ask_only", "ask_only_mode", "", packet_version)
        return {"blocked": True, "message": _ASK_ONLY_RESPONSES.get(tool_name, "I can discuss that conceptually — let me have Alanzo follow up with specifics.")}

    compliance = intel_packet.get("compliance_context") or {}
    threshold = compliance.get("requires_human_approval_above")
    if threshold and call_ctx:
        price = getattr(call_ctx, "last_price_mentioned", None)
        if price and price > threshold * 100:
            approval_id = create_approval_request(
                lead_id=lead_id, call_sid=call_sid,
                approval_type="price_threshold", requested_action=tool_name,
                risk_reason=f"price_{price//100}_above_threshold_{threshold}",
                context_snapshot={"price_mentioned": price, "threshold": threshold},
                priority="high",
            )
            if call_ctx:
                call_ctx.approval_pending = approval_id
            write_tool_gate_log(lead_id, call_sid, tool_name, "ask_operator_required", "threshold_exceeded", f"price_above_{threshold}", packet_version)
            return {"blocked": True, "message": "I want to make sure we get you the right number on that. Let me loop in my team real quick."}

    write_tool_gate_log(lead_id, call_sid, tool_name, level, "allowed", "", packet_version)
    return {"blocked": False, "level": level}


def _resolve_approval(approval_id: str, answer: str, call_ctx) -> None:
    from backend.lib.db import resolve_approval_request, _get_client
    approved = answer.strip().lower() in ("yes", "approved", "ok", "go ahead", "y", "approve")
    status = "approved" if approved else "rejected"
    resolve_approval_request(approval_id, "operator", status, answer)
    if call_ctx is None:
        return
    call_ctx.approval_pending = None
    if approved:
        try:
            client = _get_client()
            req = client.table("approval_requests").select("requested_action").eq("id", approval_id).limit(1).execute()
            if req.data:
                action = req.data[0].get("requested_action", "")
                perms = call_ctx.action_permissions or {}
                perms[action] = {"level": "book_appointment", "scope": "call", "granted_by": "operator"}
                call_ctx.action_permissions = perms
                if call_ctx.intel_packet:
                    call_ctx.intel_packet["action_permissions"] = perms
        except Exception:
            pass
        call_ctx.runtime_instruction = f"[Operator approved. You may proceed with: {answer}]"
        call_ctx.packet_state = "approved"
    else:
        call_ctx.runtime_instruction = "[Operator declined. Use safe fallback language and offer to schedule a callback.]"


def execute_tool(
    tool_name: str,
    tool_input: dict,
    call_ctx=None,
    lf_trace=None,
) -> str:
    logger.info("execute_tool name={} input={}", tool_name, tool_input)

    try:
        gate = _preflight_gate(tool_name, tool_input, call_ctx)
        if gate["blocked"]:
            return gate["message"]

        if tool_name == "book_appointment":
            result = _book_appointment(tool_input)

        elif tool_name == "send_followup_sms":
            result = _send_followup_sms(tool_input)

        elif tool_name == "set_disposition":
            result = _set_disposition(tool_input, call_ctx)

        elif tool_name == "schedule_followup":
            result = _schedule_followup(tool_input)

        elif tool_name == "end_call":
            result = _end_call(tool_input)
            if call_ctx is not None:
                call_ctx.call_should_end = True
                logger.info("end_call tool set call_should_end=True")

        elif tool_name == "transfer_call":
            result = _transfer_call(tool_input, call_ctx)

        elif tool_name == "schedule_callback":
            result = _schedule_callback(tool_input, call_ctx)

        elif tool_name == "ask_operator":
            result = _ask_operator(tool_input, call_ctx)

        elif tool_name == "send_followup_email":
            result = _send_followup_email(tool_input, call_ctx)

        elif tool_name == "get_offer_range":
            result = _get_offer_range(tool_input)

        elif tool_name == "send_offer_summary":
            result = _send_offer_summary(tool_input, call_ctx)

        elif tool_name == "collect_and_send_email":
            result = _collect_and_send_email(tool_input, call_ctx)

        elif tool_name == "drop_voicemail":
            result = _drop_voicemail(tool_input, call_ctx)

        else:
            logger.warning("unknown tool called name={}", tool_name)
            result = "Tool not found."

        try:
            from backend.observability import trace_tool_call
            trace_tool_call(lf_trace, tool_name, tool_input, result)
        except Exception:
            pass

        return result

    except Exception as e:
        logger.exception("tool execution failed tool={} error={}", tool_name, str(e))
        return "Tool execution failed."



def _send_offer_summary(inp: dict, call_ctx=None) -> str:
    seller_phone = inp.get("seller_phone", "").strip()
    offer_low = int(inp.get("offer_low") or 0)
    offer_high = int(inp.get("offer_high") or 0)
    address = inp.get("address", "").strip()
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    if not seller_phone and call_ctx:
        seller_phone = getattr(call_ctx, "seller_phone", "")
    if not seller_phone:
        return "What is the best number to text that to?"
    if not offer_low or not offer_high:
        try:
            from backend.lib.db import get_lead_with_property
            lead = get_lead_with_property(lead_id)
            prop = (lead.get("properties") or {}) if lead else {}
            mao = prop.get("mao")
            if mao:
                offer_low = int(int(mao) * 0.95 / 100)
                offer_high = int(int(mao) * 1.05 / 100)
        except Exception:
            pass
    if not offer_low:
        return "Let me have Alanzo follow up with the exact number — he handles the final offers."
    body = (
        f"Hey — Sophia from San Joaquin House Buyers. "
        f"Cash offer range for {address or 'your property'}: "
        f"${offer_low:,} – ${offer_high:,}. "
        f"As-is, no repairs, fast close. "
        f"Reply or call to discuss."
    )
    try:
        from backend.alerts.sms import send_sms
        send_sms(to=seller_phone, body=body)
        logger.info("send_offer_summary sent lead_id={}", lead_id)
        return f"Sent! Check your texts — offer range is ${offer_low:,} to ${offer_high:,}."
    except Exception as e:
        logger.exception("send_offer_summary failed error={}", str(e))
        return "Had trouble sending that. Let me have Alanzo follow up directly."


def _collect_and_send_email(inp: dict, call_ctx=None) -> str:
    email = inp.get("email", "").strip()
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    if not email:
        return "What email address should I send that to?"
    if lead_id and email:
        try:
            from backend.lib.db import _get_client
            _get_client().table("leads").update({"owner_email": email}).eq("id", lead_id).execute()
        except Exception:
            pass
    offer_low = int(inp.get("offer_low") or 0)
    offer_high = int(inp.get("offer_high") or 0)
    address = inp.get("address", "").strip()
    first_name = getattr(call_ctx, "seller_name", "") or "there"
    try:
        from backend.alerts.email import send_offer_summary_email
        sent = send_offer_summary_email(to=email, first_name=first_name, address=address, offer_low=offer_low or 150000, offer_high=offer_high or 175000, lead_id=lead_id)
        return "Sent! Check your inbox." if sent else "Had trouble with that email. Can I text you instead?"
    except Exception as e:
        logger.exception("collect_and_send_email failed error={}", str(e))
        return "Had trouble sending. Can I text you instead?"


def _drop_voicemail(inp: dict, call_ctx=None) -> str:
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    script = inp.get("script", "standard")
    scripts = {
        "standard": "Hey — this is Sophia with San Joaquin House Buyers. I was reaching out about your property. Give us a call back when you get a chance. Have a good one.",
        "callback": "Hey — Sophia with San Joaquin House Buyers. Just following up — we had talked about your property. Call me back when you get a chance.",
        "urgent": "Hey — Sophia with San Joaquin House Buyers. Wanted to touch base about your property — we may have a buyer lined up. Call us back soon.",
    }
    message = scripts.get(script, scripts["standard"])
    logger.info("drop_voicemail lead_id={} script={}", lead_id, script)
    return f"Voicemail left: {message}"


def _book_appointment(inp: dict) -> str:
    lead_id = inp.get("lead_id", "")
    date_str = inp.get("date", "")
    time_str = inp.get("time", "")
    address = inp.get("address", "")
    seller_phone = inp.get("seller_phone", "")
    seller_name = inp.get("seller_name") or "there"
    owner_phone = os.environ.get("OWNER_PHONE", "")
    dt_pacific = None

    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        dt_pacific = _PACIFIC.localize(dt_naive)
        dt_display = dt_naive.strftime("%A %b %d at %I:%M %p")
        day_display = dt_naive.strftime("%A")
        time_display = dt_naive.strftime("%I:%M %p")
    except ValueError:
        logger.warning("invalid appointment datetime date={} time={}", date_str, time_str)
        dt_display = f"{date_str} at {time_str}"
        day_display = date_str
        time_display = time_str

    if lead_id:
        update_lead_stage(lead_id, "walkthrough_booked")
        if dt_pacific:
            update_lead_appointment(lead_id, dt_pacific.isoformat())

    confirmation_msg = (
        f"Hey {seller_name}, Sophia here — "
        f"we're confirmed for {day_display} at "
        f"{time_display} at {address}. "
        f"Looking forward to meeting you."
    )

    if seller_phone:
        try:
            send_sms(to=seller_phone, body=confirmation_msg)
        except Exception as sms_err:
            logger.warning("seller confirmation sms failed error={}", str(sms_err))

    if owner_phone:
        try:
            send_sms(to=owner_phone, body=f"Walkthrough booked:\n{seller_name}\n{address}\n{dt_display}")
        except Exception as owner_sms_err:
            logger.warning("owner alert sms failed error={}", str(owner_sms_err))

    logger.info("appointment booked lead_id={} address={}", lead_id, address)
    return f"Appointment booked for {dt_display}."


def _send_followup_sms(inp: dict) -> str:
    to = inp.get("to", "").strip()
    message = inp.get("message", "").strip()
    lead_id = inp.get("lead_id", "")

    if not to or not message:
        logger.warning("followup sms missing fields")
        return "SMS not sent. Missing phone number or message."

    try:
        send_sms(to=to, body=message)
        insert_sms({
            "lead_id": lead_id or None,
            "direction": "outbound",
            "body": message,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("followup sms sent to={} lead_id={}", to, lead_id)
        return "Follow-up SMS sent."
    except Exception as e:
        logger.exception("followup sms failed error={}", str(e))
        return "SMS sending failed."


def _set_disposition(inp: dict, call_ctx) -> str:
    disposition = inp.get("disposition", "").upper().strip()
    valid = {"HOT", "WARM", "COLD", "DEAD"}

    if disposition not in valid:
        return "Invalid disposition."

    if call_ctx is not None:
        call_ctx.disposition = disposition

    logger.info("set_disposition disposition={}", disposition)
    return f"Disposition set to {disposition}."


def _schedule_followup(inp: dict) -> str:
    lead_id = inp.get("lead_id", "")
    priority = inp.get("priority", "medium")
    notes = inp.get("notes", "").strip()
    callback_time = inp.get("callback_time", "").strip()

    if callback_time:
        notes = f"{notes} | Callback: {callback_time}" if notes else f"Callback: {callback_time}"

    try:
        followup_id = create_followup(
            lead_id=lead_id,
            priority=priority,
            followup_type="call",
            notes=notes,
            created_by="sophia",
        )
        logger.info("followup created id={} lead_id={}", followup_id, lead_id)
        return f"Follow-up scheduled ({priority})."
    except Exception as e:
        logger.exception("schedule_followup failed error={}", str(e))
        return "Failed to schedule follow-up."


def _end_call(inp: dict) -> str:
    reason = inp.get("reason", "other")
    lead_id = inp.get("lead_id", "")

    stage_map = {
        "appointment_booked": "walkthrough_booked",
        "not_interested": "dead",
        "callback_scheduled": "contacted",
        "wrong_number": "dead",
        "other": "contacted",
    }

    stage = stage_map.get(reason, "contacted")

    if lead_id:
        try:
            update_lead_stage(lead_id, stage)
        except Exception as stage_err:
            logger.warning("update_lead_stage failed error={}", str(stage_err))

    logger.info("end_call reason={} stage={} lead_id={}", reason, stage, lead_id)
    return f"Call ended. Lead stage updated to {stage}."


def _transfer_call(inp: dict, call_ctx=None) -> str:
    reason = inp.get("reason", "seller requested human")
    lead_id = inp.get("lead_id", "")
    owner_phone = os.environ.get("OWNER_PHONE", "")

    logger.info("transfer_call reason={} lead_id={}", reason, lead_id)

    if call_ctx is not None:
        call_ctx.call_should_end = True
        call_ctx.disposition = "WARM"

    if lead_id:
        try:
            update_lead_stage(lead_id, "contacted")
        except Exception as e:
            logger.warning("transfer update_stage failed error={}", str(e))

    if owner_phone:
        try:
            alert = (
                f"Sophia is transferring a call — seller asked for a real person.\n"
                f"Reason: {reason}\n"
                f"Lead ID: {lead_id}"
            )
            send_sms(to=owner_phone, body=alert)
        except Exception as e:
            logger.warning("transfer alert sms failed error={}", str(e))

    return "Transferring you now — one moment."





def _schedule_callback(inp, call_ctx=None):
    from datetime import datetime, timezone, timedelta
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    delay_hours = float(inp.get("delay_hours") or 24)
    day_of_week = (inp.get("day_of_week") or "").strip().lower()
    notes = inp.get("notes", "").strip()
    if not lead_id:
        return "Need a lead ID."
    now = datetime.now(timezone.utc)
    callback_at = now + timedelta(hours=delay_hours)
    if day_of_week:
        days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        target = days.get(day_of_week)
        if target is not None:
            ahead = (target - now.weekday()) % 7 or 7
            callback_at = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=ahead)
    try:
        from backend.lib.db import schedule_callback
        schedule_callback(lead_id, callback_at.isoformat())
        if notes:
            from backend.lib.db import _get_client
            _get_client().table("leads").update({"callback_notes": notes}).eq("id", lead_id).execute()
        display = callback_at.strftime("%A at %I:%M %p")
        logger.info("schedule_callback lead_id={} at={}", lead_id, callback_at.isoformat())
        return f"Got it. I'll call you back {display} Pacific time."
    except Exception as e:
        logger.exception("schedule_callback failed error={}", str(e))
        return "Had trouble scheduling that."


def _ask_operator(inp, call_ctx=None):
    import time
    question = inp.get("question", "").strip()
    context = inp.get("context", "").strip()
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    owner_phone = os.environ.get("OWNER_PHONE", "")
    if not owner_phone:
        return "Operator unreachable. Using best judgment."
    query_id = f"op_{int(time.time())}"
    try:
        from backend.lib.db import _get_client
        _get_client().table("operator_queries").insert({"id": query_id, "lead_id": lead_id or None, "question": question, "context": context, "status": "pending"}).execute()
    except Exception:
        pass
    try:
        from backend.alerts.sms import send_sms
        send_sms(to=owner_phone, body=f"Sophia needs input\n{context or 'Active call'}\nQ: {question}\nReply to answer.", bypass_hours=True)
    except Exception:
        return "Couldn't reach operator. Continuing."
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(3)
        try:
            from backend.lib.db import _get_client
            row = _get_client().table("operator_queries").select("status,answer").eq("id", query_id).single().execute()
            if row.data and row.data.get("status") == "answered":
                try:
                    _get_client().table("operator_queries").update({"status": "closed"}).eq("id", query_id).execute()
                except Exception:
                    pass
                return f"Operator says: {row.data.get('answer', '')}"
        except Exception:
            pass
    return "No operator response. Using best judgment."


def _send_followup_email(inp, call_ctx=None):
    to = inp.get("to", "").strip()
    first_name = inp.get("first_name", "").strip() or (getattr(call_ctx, "seller_name", "") or "there").split()[0]
    address = inp.get("address", "").strip()
    offer_low = int(inp.get("offer_low") or 150000)
    offer_high = int(inp.get("offer_high") or 175000)
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    if not to:
        try:
            from backend.lib.db import get_lead_with_property
            lead = get_lead_with_property(lead_id)
            to = (lead or {}).get("owner_email", "")
        except Exception:
            pass
    if not to:
        return "What is the best email address to send that to?"
    if lead_id and to:
        try:
            from backend.lib.db import _get_client
            _get_client().table("leads").update({"owner_email": to}).eq("id", lead_id).execute()
        except Exception:
            pass
    try:
        from backend.alerts.email import send_offer_summary_email
        sent = send_offer_summary_email(to=to, first_name=first_name, address=address, offer_low=offer_low, offer_high=offer_high, lead_id=lead_id)
        return "Sent! Check your inbox." if sent else "Had trouble sending that email."
    except Exception as e:
        logger.exception("send_followup_email failed error={}", str(e))
        return "Had trouble with that. Can I text you instead?"


def _get_offer_range(inp: dict) -> str:
    address = inp.get("address", "").strip()
    lead_id = inp.get("lead_id", "")

    if not address:
        return "I need to walk through the property first to give you a real number."

    try:
        from backend.lib.db import get_lead_with_property
        lead = get_lead_with_property(lead_id) if lead_id else None
        prop = (lead.get("properties") or {}) if lead else {}

        arv_cents = prop.get("estimated_arv")
        mao_cents = prop.get("mao")
        confidence = prop.get("arv_confidence", "low")

        if arv_cents and mao_cents:
            arv = int(arv_cents) // 100
            mao = int(mao_cents) // 100
            low = int(mao * 0.95)
            high = int(mao * 1.05)

            confidence_phrase = {
                "high": "Based on several recent sales in your area",
                "medium": "Based on what I'm seeing in your area",
                "low": "Comps are a little thin out there, but roughly",
            }.get(confidence, "Based on what I'm seeing")

            return (
                f"{confidence_phrase}, we'd probably be looking "
                f"somewhere in the ${low:,} to ${high:,} range. "
                f"That's before we take a look inside — "
                f"once we walk through the number gets more precise. "
                f"Does that ballpark work for your situation?"
            )

    except Exception as e:
        logger.warning("get_offer_range db lookup failed error={}", str(e))

    return (
        "So I want to give you a real number, not just throw something out. "
        "Based on what I'm seeing for your area we're probably in a reasonable range — "
        "but honestly the number gets more precise once we actually walk through. "
        "Would that work?"
    )
