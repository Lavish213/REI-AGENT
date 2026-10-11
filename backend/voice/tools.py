import os
from datetime import datetime, timezone

import pytz
from loguru import logger

from backend.lib.db import (
    create_followup,
    update_lead_stage,
)
from backend.alerts.sms import send_sms


_PACIFIC = pytz.timezone("America/Los_Angeles")


SOPHIA_TOOLS = [
    {
        "name": "get_available_appointments",
        "description": "Read approved open walkthrough slots before proposing a date. Times are shown in Pacific local time.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
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
                "confirmed": {"type": "boolean", "description": "Seller explicitly confirmed date, time, timezone, and address"},
            },
            "required": ["date", "time", "address", "lead_id", "seller_phone", "confirmed"],
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
                "callback_time": {"type": "string", "description": "Seller-confirmed ISO 8601 timestamp with timezone offset; ask for an exact date and time first"},
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
                "date": {"type": "string", "description": "Exact future date YYYY-MM-DD"},
                "time": {"type": "string", "description": "Pacific local time HH:MM"},
                "delay_hours": {"type": "number", "description": "Only an explicitly requested relative delay"},
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


def write_tool_gate_log(*args, **kwargs):
    try:
        from backend.lib.db import write_tool_gate_log as persist_log
        return persist_log(*args, **kwargs)
    except Exception as error:
        logger.warning("tool_gate_log_unavailable error={}", str(error))
        return None


def _preflight_gate(tool_name: str, tool_input: dict, call_ctx) -> dict:
    from backend.contracts.intel_packet import (
        ALWAYS_ALLOWED_TOOLS, GATED_TOOLS, get_permission_level, is_permission_expired
    )
    from backend.lib.db import create_approval_request

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
    if fallback_mode and tool_name in _RISKY_TOOLS_MAP and tool_name != "book_appointment":
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "fallback_blocked", "system_degraded", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "System unavailable right now.")}

    conflict_active = getattr(call_ctx, "conflict_active", False) if call_ctx else False
    approved_permission = ((getattr(call_ctx, "action_permissions", None) or {}).get(tool_name) or {}) if call_ctx else {}
    if conflict_active and tool_name in _RISKY_TOOLS_MAP and approved_permission.get("granted_by") != "operator":
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
        if tool_name == "book_appointment":
            return {"blocked": False, "level": "book_appointment"}
        return {"blocked": True, "message": "No verified permissions are available. Let the team approve this action first."}

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

    expected_level = {"book_appointment": "book_appointment", "get_offer_range": "quote_range", "send_offer_summary": "send_summary", "send_followup_email": "send_summary", "collect_and_send_email": "send_summary"}.get(tool_name)
    if expected_level and level != expected_level:
        return {"blocked": True, "message": "This action needs specific operator permission."}

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
                perms[action] = {"level": {"book_appointment": "book_appointment", "get_offer_range": "quote_range"}.get(action, "send_summary"), "scope": "call", "granted_by": "operator"}
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
    logger.info("execute_tool name={}", tool_name)
    tool_input = dict(tool_input)
    if call_ctx is not None:
        bound_lead = getattr(call_ctx, "lead_id", "")
        requested_lead = tool_input.get("lead_id", "")
        if requested_lead and requested_lead != bound_lead:
            return "Action refused: the lead does not match this call."
        if bound_lead:
            tool_input["lead_id"] = bound_lead
        bound_phone = getattr(call_ctx, "seller_phone", "")
        phone_fields = ("to", "seller_phone") if tool_name == "send_followup_sms" else ("seller_phone",)
        for field in phone_fields:
            if field in tool_input:
                if not bound_phone:
                    return "Action refused: this call has no verified seller phone."
                tool_input[field] = bound_phone
        if getattr(call_ctx, "kill_switch_active", False) and tool_name not in ("end_call", "set_disposition", "transfer_call"):
            return "Action refused: human review is required."

    try:
        gate = _preflight_gate(tool_name, tool_input, call_ctx)
        if gate["blocked"]:
            return gate["message"]

        if tool_name == "get_available_appointments":
            from backend.lib.db import list_walkthrough_availability
            slots = list_walkthrough_availability()
            result = "Available walkthrough times: " + "; ".join(datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00")).astimezone(_PACIFIC).strftime("%Y-%m-%d %H:%M %Z") for slot in slots[:10]) if slots else "No approved open slots are available. Offer a human callback."

        elif tool_name == "book_appointment":
            result = _book_appointment(tool_input, call_ctx)

        elif tool_name == "send_followup_sms":
            result = _send_followup_sms(tool_input)

        elif tool_name == "set_disposition":
            result = _set_disposition(tool_input, call_ctx)

        elif tool_name == "schedule_followup":
            result = _schedule_followup(tool_input)

        elif tool_name == "end_call":
            if tool_input.get("reason") == "appointment_booked" and not getattr(call_ctx, "appointment_set", False):
                return "Call remains open: no appointment has been confirmed."
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
        if not send_sms(to=seller_phone, body=body, lead_id=lead_id):
            return "Text delivery could not be confirmed. Offer a human follow-up."
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
    if offer_low <= 0 or offer_high < offer_low:
        return "No verified offer is available. Ask the owner to approve pricing first."
    try:
        from backend.alerts.email import send_offer_summary_email
        sent = send_offer_summary_email(to=email, first_name=first_name, address=address, offer_low=offer_low, offer_high=offer_high, lead_id=lead_id)
        return "Sent! Check your inbox." if sent else "Had trouble with that email. Can I text you instead?"
    except Exception as e:
        logger.exception("collect_and_send_email failed error={}", str(e))
        return "Had trouble sending. Can I text you instead?"


def _drop_voicemail(inp: dict, call_ctx=None) -> str:
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    script = inp.get("script", "standard")
    logger.info("drop_voicemail lead_id={} script={}", lead_id, script)
    return "Voicemail delivery is unavailable. No voicemail was sent."


def _book_appointment(inp: dict, call_ctx=None) -> str:
    from backend.lib.db import reserve_voice_appointment
    from backend.voice.scheduling import local_slot
    lead_id = inp.get("lead_id", "")
    address = inp.get("address", "").strip()
    if not lead_id or not address or inp.get("confirmed") is not True:
        return "Appointment not booked. Confirm the exact date, time, Pacific timezone, and address with the seller first."
    try:
        slot = local_slot(inp.get("date", ""), inp.get("time", ""))
        reservation_id = reserve_voice_appointment(lead_id, slot.astimezone(timezone.utc).isoformat(), address)
    except Exception as error:
        logger.warning("appointment_not_reserved lead_id={} error={}", lead_id, str(error))
        return "Appointment not booked. That time could not be reserved; offer a different time or a human callback."
    if call_ctx is not None:
        call_ctx.appointment_set = True
        call_ctx.pre_close_done = True
    display = slot.strftime("%A %B %d, %Y at %I:%M %p %Z")
    phone = inp.get("seller_phone", "")
    sms_sent = send_sms(to=phone, body=f"Walkthrough confirmed: {display}, {address}.", lead_id=lead_id) if phone else False
    suffix = " Confirmation text accepted for delivery." if sms_sent else " Confirmation text was not sent."
    return f"Appointment booked for {display} at {address}. Reservation {reservation_id}." + suffix


def _send_followup_sms(inp: dict) -> str:
    to = inp.get("to", "").strip()
    message = inp.get("message", "").strip()
    if not to or not message:
        return "SMS not sent. Missing phone number or message."
    sent = send_sms(to=to, body=message, lead_id=inp.get("lead_id", ""))
    return "Follow-up SMS accepted for delivery." if sent else "SMS not sent. Offer a human follow-up."


def _set_disposition(inp: dict, call_ctx) -> str:
    disposition = inp.get("disposition", "").upper().strip()
    valid = {"HOT", "WARM", "COLD", "DEAD"}

    if disposition not in valid:
        return "Invalid disposition."

    if call_ctx is not None:
        call_ctx.disposition = disposition

    logger.info("set_disposition disposition={}", disposition)
    try:
        from backend.karpathys import emitter as _ke
        import asyncio as _aio
        _sid = getattr(call_ctx, "call_sid", "") or "" if call_ctx else ""
        _lid = getattr(call_ctx, "lead_id", None) if call_ctx else None
        _ctx_lead = getattr(call_ctx, "lead", {}) if call_ctx else {}
        _name = (_ctx_lead.get("owner_first_name") or "") if _ctx_lead else ""
        _phone = (_ctx_lead.get("owner_phone") or "") if _ctx_lead else ""
        if _sid:
            _aio.create_task(_ke.emit_disposition_action(
                call_sid=_sid,
                lead_id=str(_lid) if _lid else None,
                disposition=disposition,
                full_name=_name,
                phone=_phone,
            ))
    except Exception:
        pass
    return f"Disposition set to {disposition}."


def _schedule_followup(inp: dict) -> str:
    lead_id = inp.get("lead_id", "")
    priority = inp.get("priority", "medium")
    notes = inp.get("notes", "").strip()
    callback_time = inp.get("callback_time", "").strip()

    if not callback_time:
        return "Ask the seller for an exact callback date and time before scheduling."
    try:
        scheduled = datetime.fromisoformat(callback_time.replace("Z", "+00:00"))
        if scheduled.tzinfo is None or not 0 < (scheduled - datetime.now(timezone.utc)).total_seconds() <= 180 * 86400:
            return "Callback must have a timezone and be within the next 180 days."
    except ValueError:
        return "Ask for an exact callback date and time; the requested timestamp is invalid."

    try:
        followup_id = create_followup(
            lead_id=lead_id,
            priority=priority,
            followup_type="call",
            notes=notes,
            created_by="sophia",
            scheduled_at=scheduled.astimezone(timezone.utc).isoformat(),
        )
        if not followup_id:
            return "Failed to save follow-up. No callback has been scheduled."
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
    from backend.alerts.sms import _e164
    from backend.lib.signalwire_rest import signalwire_post
    from xml.sax.saxutils import escape
    owner_phone = _e164(os.environ.get("OWNER_PHONE", ""))
    call_sid = getattr(call_ctx, "_call_sid", "")
    if not owner_phone or not call_sid:
        return "Transfer failed: a live call and an owner phone number are required."
    try:
        laml = '<Response><Dial timeout="30">' + escape(owner_phone) + '</Dial></Response>'
        signalwire_post(f"Calls/{call_sid}.json", {"Twiml": laml})
    except Exception as error:
        logger.warning("warm_transfer_failed error={}", str(error))
        return "Transfer failed. Offer to schedule a callback with our team."
    if call_ctx is not None:
        call_ctx.call_should_end = True
    return "Transfer accepted by the phone provider."


def _schedule_callback(inp, call_ctx=None):
    from backend.lib.db import save_callback
    from backend.voice.scheduling import callback_slot
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    if not lead_id:
        return "Callback not scheduled: no lead is associated with this call."
    try:
        slot = callback_slot(inp)
        save_callback(lead_id, slot.astimezone(timezone.utc).isoformat(), inp.get("notes", ""))
    except Exception as error:
        logger.warning("callback_not_saved lead_id={} error={}", lead_id, str(error))
        return "Callback not scheduled. Please confirm a future calendar date and local time, or an explicit delay."
    if call_ctx is not None:
        call_ctx.callback_set = True
    return "Callback saved for " + slot.strftime("%A %B %d, %Y at %I:%M %p %Z") + "."


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
    import asyncio as _asyncio
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(time.sleep, 2).result(timeout=3)
            else:
                time.sleep(2)
        except Exception:
            time.sleep(2)
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
    return "No operator response in 30s. Using best judgment."


def _send_followup_email(inp, call_ctx=None):
    to = inp.get("to", "").strip()
    first_name = inp.get("first_name", "").strip() or (getattr(call_ctx, "seller_name", "") or "there").split()[0]
    address = inp.get("address", "").strip()
    offer_low = int(inp.get("offer_low") or 0)
    offer_high = int(inp.get("offer_high") or 0)
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
    if offer_low <= 0 or offer_high < offer_low:
        return "No verified offer is available. Ask the team to approve pricing first."
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
            mao_raw = int(mao_cents)
            mao = mao_raw if mao_raw > 10000 else mao_raw * 100
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
