import os
from datetime import datetime, timezone

import httpx
import pytz
from loguru import logger

from backend.lib.db import (
    get_lead_with_property,
    update_lead_call_outcome,
)

PACIFIC = pytz.timezone("America/Los_Angeles")
NO_ANSWER_SECONDS = 25


def _is_calling_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def _get_signalwire_base() -> str:
    space = os.environ["SIGNALWIRE_SPACE"]
    if not space.startswith("http"):
        space = f"https://{space}"
    return space


def _make_call(to_phone: str, lead_id: str) -> dict:
    project_id = os.environ["SIGNALWIRE_PROJECT_ID"]
    token = os.environ["SIGNALWIRE_TOKEN"]
    from_phone = os.environ["SIGNALWIRE_PHONE"]
    railway_url = os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("PUBLIC_URL", "")

    callback_url = f"{railway_url}/api/voice/outbound-webhook/{lead_id}"
    status_url = f"{railway_url}/api/voice/outbound-status/{lead_id}"

    base = _get_signalwire_base()
    url = f"{base}/api/laml/2010-04-01/Accounts/{project_id}/Calls"

    with httpx.Client() as client:
        resp = client.post(
            url,
            auth=(project_id, token),
            data={
                "From": from_phone,
                "To": to_phone,
                "Url": callback_url,
                "StatusCallback": status_url,
                "StatusCallbackMethod": "POST",
                "Timeout": str(NO_ANSWER_SECONDS),
                "MachineDetection": "DetectMessageEnd",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "call_sid": data.get("sid", ""),
            "status": data.get("status", ""),
        }


def _get_first_name(lead: dict, prop: dict) -> str:
    owner = lead.get("owner_name") or (prop or {}).get("owner_name") or ""
    parts = owner.strip().split()
    return parts[0] if parts else "there"


def _get_phone_list(prop: dict) -> list[str]:
    phones = prop.get("callable_phones")
    if not phones:
        return []
    if isinstance(phones, list):
        return [p for p in phones if p]
    return []


def call_lead(lead_id: str, bypass_cooldown: bool = False) -> dict:
    lead = get_lead_with_property(lead_id)
    if not lead:
        logger.error("call_lead lead_not_found lead_id={}", lead_id)
        return {"success": False, "reason": "lead_not_found"}

    prop = lead.get("properties") or {}

    if not _is_calling_hours():
        logger.warning("call_lead outside_hours lead_id={}", lead_id)
        return {"success": False, "reason": "outside_hours"}

    if lead.get("opted_out"):
        return {"success": False, "reason": "opted_out"}

    if lead.get("dnc_blocked"):
        return {"success": False, "reason": "dnc_blocked"}

    phones = _get_phone_list(prop)
    if not phones:
        logger.warning("call_lead no_phones lead_id={}", lead_id)
        return {"success": False, "reason": "no_phones"}

    last_called_raw = lead.get("last_called_at")
    if last_called_raw and not bypass_cooldown:
        last_called = datetime.fromisoformat(last_called_raw.replace("Z", "+00:00"))
        hours_since = (datetime.now(timezone.utc) - last_called).total_seconds() / 3600
        if hours_since < 72:
            return {"success": False, "reason": "called_recently"}

    score = prop.get("distress_score", 0)
    if score < 50:
        return {"success": False, "reason": "score_too_low"}

    if not prop.get("estimated_arv"):
        return {"success": False, "reason": "no_arv"}

    callback_at = lead.get("callback_scheduled_at")
    if callback_at:
        cb_dt = datetime.fromisoformat(callback_at.replace("Z", "+00:00"))
        if cb_dt > datetime.now(timezone.utc):
            pass

    active_call = _check_active_call(lead_id)
    if active_call:
        return {"success": False, "reason": "call_in_progress"}

    first_name = _get_first_name(lead, prop)
    primary_phone = phones[0]

    logger.info("call_lead initiating lead_id={} phone={} score={}", lead_id, primary_phone, score)

    try:
        result = _make_call(primary_phone, lead_id)
        update_lead_call_outcome(lead_id, "initiated", result["call_sid"])
        logger.info("call_lead initiated lead_id={} sid={}", lead_id, result["call_sid"])
        return {
            "success": True,
            "call_sid": result["call_sid"],
            "phone": primary_phone,
            "lead_id": lead_id,
            "first_name": first_name,
        }
    except Exception as e:
        logger.error("call_lead failed lead_id={} error={}", lead_id, str(e))
        update_lead_call_outcome(lead_id, "failed", "")
        return {"success": False, "reason": "signalwire_error", "error": str(e)}


def _check_active_call(lead_id: str) -> bool:
    try:
        project_id = os.environ["SIGNALWIRE_PROJECT_ID"]
        token = os.environ["SIGNALWIRE_TOKEN"]
        base = _get_signalwire_base()
        url = f"{base}/api/laml/2010-04-01/Accounts/{project_id}/Calls"

        with httpx.Client() as client:
            resp = client.get(
                url,
                auth=(project_id, token),
                params={"Status": "in-progress"},
                timeout=10,
            )
            data = resp.json()
            calls = data.get("calls", [])
            return len(calls) > 0
    except Exception as e:
        logger.warning("check_active_call error={}", str(e))
        return False


def build_voicemail_laml(lead: dict, prop: dict, language: str = "en") -> str:
    first_name = _get_first_name(lead, prop)
    address = prop.get("address", "your property")
    agent_phone = os.environ.get("SIGNALWIRE_PHONE", "")

    if language == "es":
        say_text = (
            f"Oye {first_name} — te habla Sophia de San Joaquin House Buyers "
            f"sobre tu propiedad en {address}. "
            f"Quiero hacerte una oferta en efectivo — sin reparaciones, sin agente, cerramos rápido. "
            f"Llámame o mándame un mensaje al {agent_phone}. ¡Hasta luego!"
        )
    else:
        say_text = (
            f"Hey {first_name} — this is Sophia calling from San Joaquin House Buyers "
            f"about your property on {address}. "
            f"I'd love to make you a cash offer — no repairs, no agents, fast close. "
            f"Give me a call back or shoot me a text at {agent_phone}. "
            f"Hope to hear from you soon! Bye."
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna" rate="95%">{say_text}</Say>
    <Hangup/>
</Response>"""


def build_outbound_answer_laml(lead_id: str) -> str:
    railway_url = os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("PUBLIC_URL", "")
    stream_url = f"{railway_url}/voice/outbound-stream/{lead_id}"
    ws_url = stream_url.replace("https://", "wss://").replace("http://", "ws://")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""
