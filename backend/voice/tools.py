import os
from datetime import datetime, timezone

import pytz

from backend.voice import execution_context
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
                "seller_name": {"type": "string", "description": "Seller first name"},
                "confirmed": {"type": "boolean", "description": "Seller explicitly confirmed date, time, timezone, and address"},
            },
            "required": ["date", "time", "confirmed"],
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
                "message": {"type": "string", "description": "SMS under 160 characters"},
            },
            "required": ["message"],
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
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "Follow-up priority"},
                "notes": {"type": "string", "description": "Callback notes"},
                "callback_time": {"type": "string", "description": "Seller-confirmed ISO 8601 timestamp with timezone offset; ask for an exact date and time first"},
            },
            "required": ["priority", "notes"],
        },
    },
    {
        "name": "honor_stop_request",
        "description": "Call this the moment the seller asks not to be contacted again — stop, remove me, take me off your list, do not call, quit calling, or any clear refusal of further contact. Suppresses all future contact for this person, records the request, and ends the call. Never ask a follow-up question, never ask for a referral, and never try to keep them talking after calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "verbatim": {"type": "string", "description": "What the seller actually said, word for word"},
                "channel": {"type": "string", "enum": ["all", "call", "sms", "email"], "description": "Scope of the request. Use all unless the seller was explicit about one channel."},
            },
            "required": ["verbatim"],
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
            },
            "required": ["reason", "summary"],
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
            },
            "required": ["reason"],
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
            },
            "required": ["notes"],
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
            },
            "required": ["question"],
        },
    },
    {
        "name": "send_followup_email",
        "description": "Send an email to the seller with offer summary. Use when seller gives their email or asks for something in writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "offer_low": {"type": "integer"},
                "offer_high": {"type": "integer"},
            },
            "required": [],
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
            },
            "required": [],
        },
    },
    {
        "name": "send_offer_summary",
        "description": "Send a cash offer summary via SMS to the seller. Use when seller asks what your offer would be or wants the number in writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_low": {"type": "integer", "description": "Low end of offer range in dollars"},
                "offer_high": {"type": "integer", "description": "High end of offer range in dollars"},
            },
            "required": [],
        },
    },
    {
        "name": "collect_and_send_email",
        "description": "Ask seller for their email then send offer summary. Use when seller asks for something in writing but no email is on file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_low": {"type": "integer"},
                "offer_high": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "drop_voicemail",
        "description": "Leave a voicemail message when seller does not answer. Use only when call goes to voicemail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Voicemail script to use: standard, callback, or urgent"},
            },
            "required": [],
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


def _preflight_gate(tool_name: str, resolved, call_ctx) -> dict:
    from backend.contracts.intel_packet import (
        ALWAYS_ALLOWED_TOOLS, GATED_TOOLS, get_permission_level, is_permission_expired
    )
    from backend.lib.db import create_approval_request

    lead_id = resolved.lead_id
    call_sid = resolved.call_sid
    packet_version = getattr(call_ctx, "packet_version", 0) if call_ctx else 0

    if tool_name in ALWAYS_ALLOWED_TOOLS:
        return {"blocked": False, "level": "allowed"}

    if getattr(call_ctx, "kill_switch_active", False) and tool_name in execution_context.SIDE_EFFECT_TOOLS:
        return {"blocked": True, "message": "Human review is required before this action."}

    if tool_name not in GATED_TOOLS:
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "unknown_tool", "not_in_capability_registry", packet_version)
        return {"blocked": True, "message": "I'm not able to do that — let me have someone follow up."}

    if tool_name in execution_context.SIDE_EFFECT_TOOLS and not execution_context.outbound_enabled():
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "outbound_disabled", "OUTBOUND_ENABLED_not_true", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "Let me have someone follow up on that.")}

    fallback_mode = getattr(call_ctx, "fallback_mode", False) if call_ctx else False
    if fallback_mode and tool_name in _RISKY_TOOLS_MAP:
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
    if not isinstance(intel_packet, dict) or not intel_packet:
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "no_intel_packet", "deny_default", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "Let me have someone follow up on that.")}

    if intel_packet.get("safe_for_live_call") is not True:
        write_tool_gate_log(lead_id, call_sid, tool_name, "blocked", "packet_not_safe_for_live_call", "deny_default", packet_version)
        return {"blocked": True, "message": _BLOCKED_RESPONSES.get(tool_name, "Let me have someone follow up on that.")}

    level = get_permission_level(intel_packet, tool_name)
    perms = intel_packet.get("action_permissions") or {}
    if not isinstance(perms, dict):
        return {"blocked": True, "message": "Verified action permissions are unavailable."}
    perm = perms.get(tool_name) or {}
    if not isinstance(perm, dict):
        return {"blocked": True, "message": "Verified action permission is invalid."}

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

    expected_level = {"set_disposition": "send_summary", "drop_voicemail": "send_summary", "get_available_appointments": "read_availability", "book_appointment": "book_appointment", "schedule_callback": "book_appointment", "schedule_followup": "book_appointment", "send_followup_sms": "send_summary", "transfer_call": "transfer_call", "ask_operator": "ask_operator", "get_offer_range": "quote_range", "send_offer_summary": "send_summary", "send_followup_email": "send_summary", "collect_and_send_email": "send_summary"}.get(tool_name)
    if expected_level and level != expected_level:
        return {"blocked": True, "message": "This action needs specific operator permission."}

    compliance = intel_packet.get("compliance_context") or {}
    if not isinstance(compliance, dict):
        return {"blocked": True, "message": "Verified compliance permissions are unavailable."}
    threshold = compliance.get("requires_human_approval_above")
    if threshold is not None and (type(threshold) is not int or threshold <= 0):
        return {"blocked": True, "message": "Verified approval threshold is invalid."}
    if threshold and call_ctx:
        price = getattr(call_ctx, "last_price_mentioned", None)
        if price and price > threshold:
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


def execute_tool(
    tool_name: str,
    tool_input: dict,
    call_ctx=None,
    lf_trace=None,
) -> str:
    logger.info("execute_tool name={} fields={}", tool_name, execution_context.redact(tool_input))

    try:
        if tool_name == execution_context.STOP_TOOL:
            resolved = execution_context.resolve_for_stop(call_ctx)
            result = _honor_stop_request(tool_input, resolved, call_ctx)
            if call_ctx is not None:
                call_ctx.call_should_end = True
            return result

        if getattr(call_ctx, "ownership_denied", False) and tool_name in {"book_appointment", "get_offer_range", "send_offer_summary"}:
            return "Action not performed. The caller denied owning this property; human review is required."

        if getattr(call_ctx, "transcript_uncertain", False) and tool_name in execution_context.SIDE_EFFECT_TOOLS and tool_name != "end_call":
            return "Action not performed. I did not hear that clearly; please confirm the missing detail first."

        try:
            resolved = execution_context.resolve(call_ctx)
        except execution_context.ContextResolutionError as error:
            logger.warning("tool_denied_unresolved_context tool={} reason={}", tool_name, str(error))
            return "Let me have someone follow up on that."

        if getattr(call_ctx, "stop_requested", False) and tool_name != "end_call":
            logger.warning(
                "tool_denied_after_stop tool={} call_sid={}", tool_name, resolved.call_sid
            )
            return "Your stop request is acknowledged. This call is ending. Take care."

        gate = _preflight_gate(tool_name, resolved, call_ctx)
        if gate["blocked"]:
            return gate["message"]

        tool_input = execution_context.sanitize(tool_name, tool_input, resolved)

        if tool_name in execution_context.SIDE_EFFECT_TOOLS:
            recheck = _preflight_gate(tool_name, resolved, call_ctx)
            if recheck["blocked"]:
                logger.warning("tool_denied_on_recheck tool={} call_sid={}", tool_name, resolved.call_sid)
                return recheck["message"]

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
            result = _get_offer_range(tool_input, call_ctx)

        elif tool_name == "send_offer_summary":
            result = _send_offer_summary(tool_input, call_ctx)

        elif tool_name == "collect_and_send_email":
            result = _collect_and_send_email(tool_input, call_ctx)

        elif tool_name == "drop_voicemail":
            result = _drop_voicemail(tool_input, call_ctx)

        else:
            logger.warning("unknown tool called name={}", tool_name)
            result = "I'm not able to do that — let me have someone follow up."

        try:
            from backend.observability import trace_tool_call
            trace_tool_call(lf_trace, tool_name, {"fields": execution_context.redact(tool_input)}, result)
        except Exception:
            pass

        return result

    except Exception as e:
        logger.exception("tool execution failed tool={} error={}", tool_name, str(e))
        return "Tool execution failed."



def _honor_stop_request(inp: dict, resolved, call_ctx=None) -> str:
    from backend.lib import db

    channel = (inp.get("channel") or "all").strip().lower()
    if channel not in ("all", "call", "sms", "email"):
        channel = "all"

    verbatim = (inp.get("verbatim") or "").strip()

    if not resolved.seller_phone:
        logger.critical(
            "STOP_REQUEST_NO_CONTACT_POINT lead_id={} call_sid={} "
            "seller asked to stop and no phone could be resolved — "
            "locate this call in provider logs and suppress manually",
            resolved.lead_id, resolved.call_sid,
        )
        if call_ctx is not None:
            call_ctx.stop_requested = True
            call_ctx.call_should_end = True
            call_ctx.runtime_instruction = None
        return "Understood. I am ending this call. I could not confirm that your number was removed from the contact list."

    results = {
        "evidence": db.try_write(
            "stop_evidence",
            db.record_suppression_event,
            tenant_id=resolved.tenant_id,
            lead_id=resolved.lead_id,
            contact_point=resolved.seller_phone,
            contact_type="phone",
            channel=channel,
            method="verbal_stop_request",
            source="live_call",
            reason="seller_requested_no_contact",
            call_sid=resolved.call_sid,
            verbatim=verbatim,
            actor="sophia",
        ),
        "dnc": db.try_write(
            "stop_dnc", db.add_to_dnc, resolved.tenant_id, resolved.seller_phone, reason="seller_request"
        ),
        "lead_flag": db.try_write("stop_lead_flag", db.mark_lead_opted_out, resolved.lead_id),
    }

    if call_ctx is not None:
        call_ctx.stop_requested = True
        call_ctx.call_should_end = True
        call_ctx.runtime_instruction = None

    wrote = [k for k, ok in results.items() if ok]
    missed = [k for k, ok in results.items() if not ok]

    if not wrote:
        logger.critical(
            "STOP_REQUEST_UNPERSISTED lead_id={} call_sid={} phone_suffix={} "
            "stop request acknowledged but NOTHING was written — "
            "suppress this contact manually before any further outreach",
            resolved.lead_id, resolved.call_sid, resolved.seller_phone[-4:],
        )
    elif missed:
        logger.error("stop_request_partial lead_id={} wrote={} failed={}", resolved.lead_id, wrote, missed)
    else:
        logger.info("stop_request_honored lead_id={} call_sid={} channel={}",
                    resolved.lead_id, resolved.call_sid, channel)

    if not results["dnc"] or not results["lead_flag"]:
        return "Understood. I am ending this call. I could not confirm that your number was removed from the contact list."
    return "Understood — your number has been removed from our contact list. Take care."


def _verified_offer_range(lead_id: str, call_ctx=None) -> tuple[int, int] | None:
    from backend.lib.db import get_lead_with_property
    try:
        lead = get_lead_with_property(lead_id) or {}
        prop = lead.get("properties") or {}
        if isinstance(prop, list):
            prop = prop[0] if prop else {}
        ceiling = prop.get("mao")
        if type(ceiling) is not int or ceiling <= 0 or prop.get("arv_confidence") not in {"medium", "high"}:
            return None
        packet = getattr(call_ctx, "intel_packet", None) or {}
        strategy = packet.get("strategy_context") or {}
        approved_max = strategy.get("max_offer")
        if approved_max is not None:
            if type(approved_max) is not int or approved_max <= 0:
                return None
            ceiling = min(ceiling, approved_max)
        low, high = ceiling * 95 // 100 // 100, ceiling // 100
        return (low, high) if 0 < low <= high else None
    except Exception as error:
        logger.warning("offer_authority_unavailable error={}", str(error))
        return None


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
    verified = _verified_offer_range(lead_id, call_ctx)
    if not verified:
        return "No verified offer is available. Have Alanzo approve pricing first."
    offer_low, offer_high = verified
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
        return f"Text accepted for delivery — offer range is ${offer_low:,} to ${offer_high:,}."
    except Exception as e:
        logger.exception("send_offer_summary failed error={}", str(e))
        return "Had trouble sending that. Let me have Alanzo follow up directly."


def _collect_and_send_email(inp: dict, call_ctx=None) -> str:
    email = inp.get("email", "").strip()
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    if not email:
        return "What email address should I send that to?"
    verified = _verified_offer_range(lead_id, call_ctx)
    if not verified:
        return "No verified offer is available. Ask the owner to approve pricing first."
    offer_low, offer_high = verified
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
            return "Call ended. Saving the lead stage failed; no stage update is confirmed."

    logger.info("end_call reason={} stage={} lead_id={}", reason, stage, lead_id)
    return "Call ended. No lead stage update was requested." if not lead_id else f"Call ended. Lead stage updated to {stage}."


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
    from backend.lib.db import create_operator_query, get_operator_answer, close_operator_query
    from backend.alerts.sms import send_sms
    question = inp.get("question", "").strip()
    context = inp.get("context", "").strip()
    lead_id = inp.get("lead_id", "") or getattr(call_ctx, "lead_id", "")
    owner_phone = os.environ.get("OWNER_PHONE", "")
    denied = "Action not approved. Offer a human follow-up; do not promise it has been scheduled."
    if not owner_phone or not question:
        return "Operator unreachable. " + denied
    try:
        query_id = create_operator_query(lead_id, question, context)
    except Exception as error:
        logger.warning("operator_query_not_saved error={}", str(error))
        return "Operator request could not be saved. " + denied
    try:
        sent = send_sms(to=owner_phone, body=f"Sophia needs input\n{context or 'Active call'}\nQ: {question}\nReply with {query_id} followed by your answer.", bypass_hours=True)
    except Exception as error:
        logger.warning("operator_delivery_failed error={}", str(error))
        sent = False
    if not sent:
        return "Operator request was not accepted for delivery. " + denied
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            answer = get_operator_answer(query_id)
            if answer:
                close_operator_query(query_id)
                return f"Operator says: {answer}. This reply does not itself authorize a restricted tool; verified action permission is still required."
        except Exception as error:
            logger.warning("operator_answer_unavailable error={}", str(error))
            return "Operator response could not be verified. " + denied
    return "No operator response in 30 seconds. " + denied


def _send_followup_email(inp, call_ctx=None):
    to = inp.get("to", "").strip()
    lead_id = inp.get("lead_id", "")
    first_name = inp.get("first_name", "").strip() or "there"
    address = inp.get("address", "").strip()
    if not to:
        return "No verified seller email is available. Ask for a human follow-up."
    verified = _verified_offer_range(lead_id, call_ctx)
    if not verified:
        return "No verified offer is available. Ask the owner to approve pricing first."
    offer_low, offer_high = verified
    try:
        from backend.alerts.email import send_offer_summary_email
        sent = send_offer_summary_email(to=to, first_name=first_name, address=address, offer_low=offer_low, offer_high=offer_high, lead_id=lead_id)
        return "Email accepted for delivery." if sent else "Had trouble sending that email."
    except Exception as error:
        logger.warning("send_followup_email failed error={}", str(error))
        return "Had trouble sending that email."


def _get_offer_range(inp: dict, call_ctx=None) -> str:
    verified = _verified_offer_range(inp.get("lead_id", ""), call_ctx)
    if not verified:
        return "I don't have a verified offer yet. Let me have Alanzo review the property and follow up."
    low, high = verified
    return f"The verified preliminary range is ${low:,} to ${high:,}, subject to a walkthrough. Does that work for your situation?"
