from __future__ import annotations
import os
from datetime import datetime, timezone

import pytz
from loguru import logger


def _e164(raw: str) -> str:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if (raw or "").strip().startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    raise ValueError("A valid phone number is required")
from backend.lib.db import insert_sms
from backend.lib.signalwire_rest import signalwire_post

_PACIFIC = pytz.timezone("America/Los_Angeles")


def _is_tcpa_hours() -> bool:
    start = int(os.environ.get("CALLING_HOURS_START", 9))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= datetime.now(_PACIFIC).hour < end


def _from_number() -> str:
    return os.environ["SIGNALWIRE_PHONE"]


def _status_callback_url() -> str | None:
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    return f"{base}/api/voice/sms-status" if base else None


def send_sms(to: str, body: str, lead_id: str = "", bypass_hours: bool = False) -> bool:
    if os.environ.get("OUTBOUND_ENABLED", "false").lower() != "true":
        return False
    try:
        to = _e164(to)
    except ValueError:
        return False
    try:
        from backend.lib import db
        if db.phone_is_do_not_call(to):
            return False
    except Exception as error:
        logger.warning("sms_suppression_unavailable type={}", type(error).__name__)
        return False
    if lead_id:
        from backend.compliance.compliance import ComplianceEngine
        if not ComplianceEngine().check_sms_allowed(lead_id).allowed:
            return False
    if not bypass_hours and not _is_tcpa_hours():
        logger.warning("send_sms blocked outside TCPA hours to={}", to)
        return False
    try:
        identity, claimed, receipt = db.claim_message_intent("sms", to, "", body, lead_id)
        if not claimed:
            return bool(receipt)
        kwargs = {"From": _from_number(), "To": to, "Body": body}
        callback = _status_callback_url()
        if callback:
            kwargs["StatusCallback"] = callback
        message = signalwire_post("Messages.json", kwargs)
        db.accept_message_intent(identity, message["sid"])
        try:
            insert_sms({
            "lead_id": lead_id or None,
            "direction": "outbound",
            "body": body,
            "signalwire_message_id": message["sid"],
            "delivery_status": message.get("status", "queued"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as error:
            logger.error("sms_accepted_logging_pending sid={} error={}", message["sid"], str(error))
        if lead_id:
            try:
                from backend.lib.db import update_sms_contact_time
                update_sms_contact_time(lead_id, datetime.now(timezone.utc).isoformat())
            except Exception as error:
                logger.warning("sms_contact_time_not_saved error={}", str(error))
        logger.info("send_sms to={} sid={} lead_id={}", to, message["sid"], lead_id)
        return True
    except Exception as e:
        logger.error("send_sms failed to={} error={}", to, str(e))
        return False


def send_drip_sms(to: str, body: str, lead_id: str) -> bool:
    if not _is_tcpa_hours():
        logger.warning("send_drip_sms blocked outside TCPA hours")
        return False
    return send_sms(to=to, body=body, lead_id=lead_id)


def send_alert_to_owner(body: str) -> bool:
    phone = os.environ.get("ALERT_PHONE", "") or os.environ.get("OWNER_PHONE", "")
    if not phone:
        logger.warning("ALERT_PHONE and OWNER_PHONE both not set skipping owner alert")
        return False
    return send_sms(to=phone, body=body, bypass_hours=True)


def send_referral_ask_sms(to: str, first_name: str, lead_id: str) -> bool:
    body = (
        f"Hey {first_name} — Sophia here. Even if the timing isn't right for you, "
        f"do you know anyone around there thinking about selling? "
        f"We pay a referral fee. Just reply with their name. - Sophia SJ House Buyers"
    )
    return send_sms(to=to, body=body, lead_id=lead_id)


def send_offer_summary_sms(
    to: str,
    first_name: str,
    address: str,
    offer_low: int,
    offer_high: int,
    lead_id: str,
) -> bool:
    low_fmt = f"${offer_low:,}"
    high_fmt = f"${offer_high:,}"
    body = (
        f"Hey {first_name} — Sophia from SJ House Buyers. "
        f"Here's the summary: {address}, cash offer range {low_fmt}–{high_fmt}, "
        f"as-is, fast close. Questions? Just reply. - Sophia"
    )
    return send_sms(to=to, body=body, lead_id=lead_id)


def send_owner_call_digest(
    disposition: str | None,
    call_summary: str | None,
    next_best_action: str | None,
    motivation_level: int | None,
    timeline_urgency: str | None,
    address: str | None,
    lead_id: str = "",
) -> bool:
    disp = (disposition or "unknown").upper()
    emoji = {"HOT": "🔥", "WARM": "☀️", "COLD": "❄️", "DEAD": "💀"}.get(disp, "📞")
    lines = [
        f"{emoji} Call done — {disp}",
        address or "Unknown address",
        f"Summary: {call_summary or 'none'}",
        f"Motivation: {motivation_level or '?'}/10 | Timeline: {timeline_urgency or 'unknown'}",
        f"Next: {next_best_action or 'follow up'}",
    ]
    return send_alert_to_owner("\n".join(lines))
