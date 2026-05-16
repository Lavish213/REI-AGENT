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
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "time": {
                    "type": "string",
                    "description": "Time in HH:MM 24hr format",
                },
                "address": {
                    "type": "string",
                    "description": "Property address",
                },
                "lead_id": {
                    "type": "string",
                    "description": "Lead ID",
                },
                "seller_phone": {
                    "type": "string",
                    "description": "Seller phone number",
                },
                "seller_name": {
                    "type": "string",
                    "description": "Seller first name",
                },
            },
            "required": [
                "date",
                "time",
                "address",
                "lead_id",
                "seller_phone",
            ],
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
                "to": {
                    "type": "string",
                    "description": "Seller phone number",
                },
                "message": {
                    "type": "string",
                    "description": (
                        "SMS under 160 characters"
                    ),
                },
                "lead_id": {
                    "type": "string",
                    "description": "Lead ID",
                },
            },
            "required": [
                "to",
                "message",
                "lead_id",
            ],
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
                "lead_id": {
                    "type": "string",
                    "description": "Lead ID",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Follow-up priority",
                },
                "notes": {
                    "type": "string",
                    "description": "Callback notes",
                },
                "callback_time": {
                    "type": "string",
                    "description": "Requested callback timing",
                },
            },
            "required": [
                "lead_id",
                "priority",
                "notes",
            ],
        },
    },
    {
        "name": "end_call",
        "description": (
            "End the conversation after wrapping up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "appointment_booked, "
                        "not_interested, "
                        "callback_scheduled, "
                        "wrong_number, "
                        "other"
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": "Short call summary",
                },
                "lead_id": {
                    "type": "string",
                    "description": "Lead ID",
                },
            },
            "required": [
                "reason",
                "summary",
                "lead_id",
            ],
        },
    },
]


def execute_tool(
    tool_name: str,
    tool_input: dict,
    call_ctx=None,
    lf_trace=None,
) -> str:
    logger.info(
        "execute_tool name={} input={}",
        tool_name,
        tool_input,
    )

    try:
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

        else:
            logger.warning(
                "unknown tool called name={}",
                tool_name,
            )
            result = "Tool not found."

        try:
            from backend.observability import trace_tool_call

            trace_tool_call(
                lf_trace,
                tool_name,
                tool_input,
                result,
            )

        except Exception:
            pass

        return result

    except Exception as e:
        logger.exception(
            "tool execution failed tool={} error={}",
            tool_name,
            str(e),
        )
        return "Tool execution failed."


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
        dt_naive = datetime.strptime(
            f"{date_str} {time_str}",
            "%Y-%m-%d %H:%M",
        )

        dt_pacific = _PACIFIC.localize(dt_naive)

        dt_display = dt_naive.strftime(
            "%A %b %d at %I:%M %p"
        )

        day_display = dt_naive.strftime("%A")
        time_display = dt_naive.strftime("%I:%M %p")

    except ValueError:
        logger.warning(
            "invalid appointment datetime date={} time={}",
            date_str,
            time_str,
        )

        dt_display = f"{date_str} at {time_str}"
        day_display = date_str
        time_display = time_str

    if lead_id:
        update_lead_stage(
            lead_id,
            "walkthrough_booked",
        )

        if dt_pacific:
            update_lead_appointment(
                lead_id,
                dt_pacific.isoformat(),
            )

    confirmation_msg = (
        f"Hey {seller_name}, Sophia here — "
        f"we're confirmed for {day_display} at "
        f"{time_display} at {address}. "
        f"Looking forward to meeting you."
    )

    if seller_phone:
        try:
            send_sms(
                to=seller_phone,
                body=confirmation_msg,
            )

        except Exception as sms_err:
            logger.warning(
                "seller confirmation sms failed error={}",
                str(sms_err),
            )

    if owner_phone:
        owner_alert = (
            f"Walkthrough booked:\n"
            f"{seller_name}\n"
            f"{address}\n"
            f"{dt_display}"
        )

        try:
            send_sms(
                to=owner_phone,
                body=owner_alert,
            )

        except Exception as owner_sms_err:
            logger.warning(
                "owner alert sms failed error={}",
                str(owner_sms_err),
            )

    logger.info(
        "appointment booked lead_id={} address={}",
        lead_id,
        address,
    )

    return (
        f"Appointment booked for "
        f"{dt_display}."
    )


def _send_followup_sms(inp: dict) -> str:
    to = inp.get("to", "").strip()
    message = inp.get("message", "").strip()
    lead_id = inp.get("lead_id", "")

    if not to or not message:
        logger.warning(
            "followup sms missing fields"
        )
        return (
            "SMS not sent. Missing "
            "phone number or message."
        )

    try:
        send_sms(
            to=to,
            body=message,
        )

        insert_sms({
            "lead_id": lead_id or None,
            "direction": "outbound",
            "body": message,
            "sent_at": datetime.now(
                timezone.utc,
            ).isoformat(),
        })

        logger.info(
            "followup sms sent to={} lead_id={}",
            to,
            lead_id,
        )

        return "Follow-up SMS sent."

    except Exception as e:
        logger.exception(
            "followup sms failed error={}",
            str(e),
        )
        return "SMS sending failed."


def _set_disposition(
    inp: dict,
    call_ctx,
) -> str:
    disposition = (
        inp.get("disposition", "")
        .upper()
        .strip()
    )

    valid = {
        "HOT",
        "WARM",
        "COLD",
        "DEAD",
    }

    if disposition not in valid:
        return (
            "Invalid disposition."
        )

    if call_ctx is not None:
        call_ctx.disposition = disposition

    logger.info(
        "set_disposition disposition={}",
        disposition,
    )

    return (
        f"Disposition set to "
        f"{disposition}."
    )


def _schedule_followup(inp: dict) -> str:
    lead_id = inp.get("lead_id", "")
    priority = inp.get("priority", "medium")
    notes = inp.get("notes", "").strip()
    callback_time = inp.get(
        "callback_time",
        "",
    ).strip()

    if callback_time:
        if notes:
            notes = (
                f"{notes} | "
                f"Callback: {callback_time}"
            )
        else:
            notes = (
                f"Callback: {callback_time}"
            )

    try:
        followup_id = create_followup(
            lead_id=lead_id,
            priority=priority,
            followup_type="call",
            notes=notes,
            created_by="sophia",
        )

        logger.info(
            "followup created id={} lead_id={}",
            followup_id,
            lead_id,
        )

        return (
            f"Follow-up scheduled "
            f"({priority})."
        )

    except Exception as e:
        logger.exception(
            "schedule_followup failed error={}",
            str(e),
        )

        return (
            "Failed to schedule "
            "follow-up."
        )


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

    stage = stage_map.get(
        reason,
        "contacted",
    )

    if lead_id:
        try:
            update_lead_stage(
                lead_id,
                stage,
            )

        except Exception as stage_err:
            logger.warning(
                "update_lead_stage failed error={}",
                str(stage_err),
            )

    logger.info(
        "end_call reason={} stage={} lead_id={}",
        reason,
        stage,
        lead_id,
    )

    return (
        f"Call ended. "
        f"Lead stage updated to {stage}."
    )