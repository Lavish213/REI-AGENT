from __future__ import annotations
import os
from datetime import datetime, timezone

import pytz
from loguru import logger
from signalwire.rest import Client as SignalWireClient

from backend.lib.db import insert_sms

_client: SignalWireClient | None = None
_PACIFIC = pytz.timezone("America/Los_Angeles")


def _get_client() -> SignalWireClient:
    global _client
    if _client is None:
        _client = SignalWireClient(
            os.environ["SIGNALWIRE_PROJECT_ID"],
            os.environ["SIGNALWIRE_TOKEN"],
            signalwire_space_url=os.environ["SIGNALWIRE_SPACE"],
        )
        logger.info("signalwire_client_initialized")
    return _client


def _is_tcpa_hours() -> bool:
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= datetime.now(_PACIFIC).hour < end


def _from_number() -> str:
    return os.environ["SIGNALWIRE_PHONE"]


def _status_callback_url() -> str | None:
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    return f"{base}/api/voice/sms-status" if base else None


def send_sms(to: str, body: str, lead_id: str = "", bypass_hours: bool = False) -> bool:
    if not bypass_hours and not _is_tcpa_hours():
        logger.warning("send_sms blocked outside TCPA hours to={}", to)
        return False
    try:
        client = _get_client()
        kwargs: dict = {"from_": _from_number(), "to": to, "body": body}
        callback = _status_callback_url()
        if callback:
            kwargs["status_callback"] = callback
        message = client.messages.create(**kwargs)
        insert_sms({
            "lead_id": lead_id or None,
            "direction": "outbound",
            "body": body,
            "signalwire_message_id": message.sid,
            "delivery_status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("send_sms to={} sid={} lead_id={}", to, message.sid, lead_id)
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
    phone = os.environ.get("ALERT_PHONE", "")
    if not phone:
        logger.warning("ALERT_PHONE not set skipping owner alert")
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
