import os
from datetime import datetime, timezone

import pytz
from loguru import logger

from backend.lib.db import update_lead_stage, update_lead_appointment, insert_sms
from backend.alerts.sms import send_sms

_PACIFIC = pytz.timezone("America/Los_Angeles")


SOPHIA_TOOLS = [
    {
        "name": "book_appointment",
        "description": "Book a property walkthrough appointment. Use when seller agrees to meet. Always confirm date and time before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Appointment date in YYYY-MM-DD format",
                },
                "time": {
                    "type": "string",
                    "description": "Appointment time in HH:MM format 24hr",
                },
                "address": {
                    "type": "string",
                    "description": "Full property address for the walkthrough",
                },
                "lead_id": {
                    "type": "string",
                    "description": "The lead ID from the call context",
                },
                "seller_phone": {
                    "type": "string",
                    "description": "Seller phone number to send confirmation",
                },
                "seller_name": {
                    "type": "string",
                    "description": "Seller first name for personalization",
                },
            },
            "required": ["date", "time", "address", "lead_id", "seller_phone"],
        },
    },
    {
        "name": "send_followup_sms",
        "description": "Send a follow-up SMS to the seller after the call. Use at end of every call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Seller phone number",
                },
                "message": {
                    "type": "string",
                    "description": "SMS message to send — keep under 160 characters",
                },
                "lead_id": {
                    "type": "string",
                    "description": "The lead ID",
                },
            },
            "required": ["to", "message", "lead_id"],
        },
    },
    {
        "name": "set_disposition",
        "description": "Classify the lead once you have enough signals. HOT=seller mentioned timeline, asked about price, agreed to appointment, or asked how the process works. WARM=engaged but not ready, open to callback. COLD=not interested now, may reconsider later. DEAD=hostile, wrong number, explicit no, or DNC request. Call this once during the call when the picture is clear.",
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
        "name": "end_call",
        "description": "End the call cleanly. Call this when conversation is complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the call is ending: appointment_booked, not_interested, callback_scheduled, wrong_number, other",
                },
                "summary": {
                    "type": "string",
                    "description": "One sentence summary of what was discussed and decided",
                },
                "lead_id": {
                    "type": "string",
                    "description": "The lead ID",
                },
            },
            "required": ["reason", "summary", "lead_id"],
        },
    },
]


def execute_tool(tool_name: str, tool_input: dict, call_ctx=None) -> str:
    logger.info("execute_tool name={} input={}", tool_name, tool_input)

    if tool_name == "book_appointment":
        return _book_appointment(tool_input)
    if tool_name == "send_followup_sms":
        return _send_followup_sms(tool_input)
    if tool_name == "set_disposition":
        return _set_disposition(tool_input, call_ctx)
    if tool_name == "end_call":
        return _end_call(tool_input)

    logger.warning("unknown tool called name={}", tool_name)
    return "Tool not found"


def _book_appointment(inp: dict) -> str:
    lead_id = inp.get("lead_id", "")
    date_str = inp.get("date", "")
    time_str = inp.get("time", "")
    address = inp.get("address", "")
    seller_phone = inp.get("seller_phone", "")
    seller_name = inp.get("seller_name", "there")
    owner_phone = os.environ.get("OWNER_PHONE", "")

    dt_pacific = None
    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        dt_pacific = _PACIFIC.localize(dt_naive)
        dt_display = dt_naive.strftime("%A %b %-d at %-I:%M %p")
        time_display = dt_naive.strftime("%-I:%M %p")
        day_display = dt_naive.strftime("%A")
    except ValueError:
        dt_display = f"{date_str} at {time_str}"
        time_display = time_str
        day_display = date_str

    if lead_id:
        update_lead_stage(lead_id, "walkthrough_booked")
        if dt_pacific is not None:
            update_lead_appointment(lead_id, dt_pacific.isoformat())

    confirmation_msg = (
        f"Hey {seller_name}! Sophia here \u2014 just confirming we're set for "
        f"{day_display} at {time_display} at {address}. "
        f"Super easy process \u2014 we'll take a quick walk through and then I'll get you "
        f"a real number same day. See you then! \U0001f3e1"
    )
    if seller_phone:
        send_sms(to=seller_phone, body=confirmation_msg)

    owner_alert = (
        f"WALKTHROUGH BOOKED\n"
        f"{seller_name} - {address}\n"
        f"{dt_display}"
    )
    if owner_phone:
        send_sms(to=owner_phone, body=owner_alert)

    logger.info("appointment booked lead_id={} date={} time={}", lead_id, date_str, time_str)
    return f"Appointment booked for {dt_display} at {address}. Confirmation sent."


def _send_followup_sms(inp: dict) -> str:
    to = inp.get("to", "")
    message = inp.get("message", "")
    lead_id = inp.get("lead_id", "")

    if to and message:
        send_sms(to=to, body=message)
        insert_sms({
            "lead_id": lead_id if lead_id else None,
            "direction": "outbound",
            "body": message,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("followup SMS sent to={} lead_id={}", to, lead_id)
        return "Follow-up SMS sent successfully."

    logger.warning("send_followup_sms missing to or message")
    return "SMS not sent — missing phone number or message."


def _set_disposition(inp: dict, call_ctx) -> str:
    disposition = inp.get("disposition", "").upper()
    valid = {"HOT", "WARM", "COLD", "DEAD"}
    if disposition not in valid:
        return f"Invalid disposition. Use one of: {', '.join(sorted(valid))}"
    if call_ctx is not None:
        call_ctx.disposition = disposition
    logger.info("set_disposition disposition={}", disposition)
    return f"Disposition set to {disposition}."


def _end_call(inp: dict) -> str:
    reason = inp.get("reason", "other")
    summary = inp.get("summary", "")
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
        update_lead_stage(lead_id, stage)

    logger.info("end_call reason={} stage={} lead_id={}", reason, stage, lead_id)
    return f"Call ended. Reason: {reason}. Lead stage updated to {stage}."
