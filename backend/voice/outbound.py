from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
import pytz
from loguru import logger

from backend.lib.db import (
    get_lead_with_property,
    update_lead_call_outcome,
)


PACIFIC = pytz.timezone("America/Los_Angeles")

NO_ANSWER_SECONDS = 25
MIN_DISTRESS_SCORE = 50
CALL_COOLDOWN_HOURS = 72

_VM_VOICE_EN = "Polly.Joanna"
_VM_RATE_EN = "95%"
_VM_VOICE_ES = "Polly.Lupe"
_VM_RATE_ES = "95%"


def _is_calling_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 8))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def _get_signalwire_base() -> str:
    space = os.environ["SIGNALWIRE_SPACE"].strip()
    if not space.startswith("http"):
        space = f"https://{space}"
    return space.rstrip("/")


def _get_public_base_url() -> str:
    url = (
        os.environ.get("RAILWAY_STATIC_URL")
        or os.environ.get("PUBLIC_URL")
        or ""
    ).strip()
    if not url:
        raise RuntimeError("PUBLIC_URL or RAILWAY_STATIC_URL missing")
    return url.rstrip("/")


def _to_ws_url(url: str) -> str:
    return url.replace("https://", "wss://").replace("http://", "ws://")


def _safe_iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        logger.warning("invalid_datetime_format value={}", value)
        return None


def _get_first_name(lead: dict, prop: dict) -> str:
    owner = (
        lead.get("owner_name")
        or (prop or {}).get("owner_name")
        or ""
    ).strip()
    parts = owner.split()
    return parts[0] if parts else "there"


def _get_phone_list(prop: dict) -> list[str]:
    phones = prop.get("callable_phones")
    if not phones or not isinstance(phones, list):
        return []
    return [str(p).strip() for p in phones if p]


def _build_signalwire_auth() -> tuple[str, str]:
    return (
        os.environ["SIGNALWIRE_PROJECT_ID"],
        os.environ["SIGNALWIRE_TOKEN"],
    )


def _make_call(to_phone: str, lead_id: str) -> dict[str, str]:
    project_id = os.environ["SIGNALWIRE_PROJECT_ID"]
    from_phone = os.environ["SIGNALWIRE_PHONE"]
    railway_url = _get_public_base_url()
    callback_url = f"{railway_url}/api/voice/outbound-webhook/{lead_id}"
    status_url = f"{railway_url}/api/voice/outbound-status/{lead_id}"
    base = _get_signalwire_base()
    url = f"{base}/api/laml/2010-04-01/Accounts/{project_id}/Calls"

    payload = {
        "From": from_phone,
        "To": to_phone,
        "Url": callback_url,
        "StatusCallback": status_url,
        "StatusCallbackMethod": "POST",
        "Timeout": str(NO_ANSWER_SECONDS),
        "MachineDetection": "DetectMessageEnd",
    }

    logger.info("signalwire_call_request lead_id={} to={} callback_url={}", lead_id, to_phone, callback_url)

    with httpx.Client() as client:
        response = client.post(url, auth=_build_signalwire_auth(), data=payload, timeout=20)
        response.raise_for_status()
        data = response.json()

    return {"call_sid": data.get("sid", ""), "status": data.get("status", "")}


_MAX_CONCURRENT_CALLS = 3
_REDIS_CONCURRENT_KEY = "rei_agent:concurrent_calls"


def _get_redis_client():
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        import redis
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


def _acquire_call_slot(lead_id: str) -> bool:
    client = _get_redis_client()
    if not client:
        return True
    try:
        import time
        pipe = client.pipeline()
        now = time.time()
        pipe.zremrangebyscore(_REDIS_CONCURRENT_KEY, "-inf", now - 900)
        pipe.zcard(_REDIS_CONCURRENT_KEY)
        _, current_count = pipe.execute()
        if current_count >= _MAX_CONCURRENT_CALLS:
            logger.warning("concurrency_limit_reached lead_id={} active={}", lead_id, current_count)
            return False
        client.zadd(_REDIS_CONCURRENT_KEY, {lead_id: now + 900})
        return True
    except Exception as e:
        logger.warning("acquire_call_slot failed error={}", str(e))
        return True


def _release_call_slot(lead_id: str) -> None:
    client = _get_redis_client()
    if not client:
        return
    try:
        client.zrem(_REDIS_CONCURRENT_KEY, lead_id)
    except Exception:
        pass


def _schedule_retry_for_disposition(lead_id: str, disposition: str, attempt_count: int) -> None:
    if attempt_count >= 3:
        logger.info("max_retries_reached lead_id={} disposition={}", lead_id, disposition)
        return
    retry_delays = {
        "no-answer": 4 * 3600,
        "busy": 1800,
        "voicemail": 24 * 3600,
    }
    delay_seconds = retry_delays.get(disposition)
    if not delay_seconds:
        return
    try:
        from backend.lib.db import schedule_lead_retry
        schedule_lead_retry(lead_id, delay_seconds=delay_seconds, attempt_count=attempt_count + 1)
        logger.info("retry_scheduled lead_id={} disposition={} delay_hours={:.1f}", lead_id, disposition, delay_seconds / 3600)
    except Exception as e:
        logger.warning("schedule_retry failed lead_id={} error={}", lead_id, str(e))


def _check_active_call(lead_id: str) -> bool:
    client = _get_redis_client()
    if not client:
        return False
    try:
        import time
        client.zremrangebyscore(_REDIS_CONCURRENT_KEY, "-inf", time.time() - 900)
        count = client.zcard(_REDIS_CONCURRENT_KEY)
        if count >= _MAX_CONCURRENT_CALLS:
            logger.warning("active_call_detected lead_id={} count={}", lead_id, count)
            return True
        return False
    except Exception as e:
        logger.warning("check_active_call_failed lead_id={} error={}", lead_id, str(e))
        return False


def call_lead(
    lead_id: str,
    bypass_cooldown: bool = False,
) -> dict[str, Any]:
    try:
        from backend.compliance.compliance import ComplianceEngine
        engine = ComplianceEngine()
        result = engine.check_call_allowed(lead_id)

        if not result.allowed:
            logger.warning("outbound_compliance_blocked lead_id={} reason={}", lead_id, result.reason)
            return {"success": False, "reason": result.reason}

        lead = get_lead_with_property(lead_id)

        if not lead:
            logger.error("call_lead_lead_not_found lead_id={}", lead_id)
            return {"success": False, "reason": "lead_not_found"}

        prop = lead.get("properties") or {}

        if not _is_calling_hours():
            logger.warning("call_lead_outside_hours lead_id={}", lead_id)
            return {"success": False, "reason": "outside_hours"}

        if lead.get("opted_out"):
            return {"success": False, "reason": "opted_out"}

        if lead.get("dnc_blocked"):
            return {"success": False, "reason": "dnc_blocked"}

        phones = _get_phone_list(prop)

        if not phones:
            logger.warning("call_lead_no_phones lead_id={}", lead_id)
            return {"success": False, "reason": "no_phones"}

        if not bypass_cooldown:
            last_called = _safe_iso_to_datetime(lead.get("last_called_at"))
            if last_called:
                hours_since = (datetime.now(timezone.utc) - last_called).total_seconds() / 3600
                if hours_since < CALL_COOLDOWN_HOURS:
                    return {"success": False, "reason": "called_recently"}

        score = int(prop.get("distress_score", 0))

        if score < MIN_DISTRESS_SCORE:
            return {"success": False, "reason": "score_too_low"}

        if not prop.get("estimated_arv"):
            return {"success": False, "reason": "no_arv"}

        callback_at = _safe_iso_to_datetime(lead.get("callback_scheduled_at"))
        if callback_at and callback_at > datetime.now(timezone.utc):
            logger.info("call_lead_callback_pending lead_id={} callback_at={}", lead_id, callback_at.isoformat())

        if _check_active_call(lead_id):
            return {"success": False, "reason": "call_in_progress"}

        if not _acquire_call_slot(lead_id):
            return {"success": False, "reason": "at_capacity"}

        first_name = _get_first_name(lead, prop)
        primary_phone = phones[0]

        logger.info("call_lead_initiating lead_id={} phone={} score={}", lead_id, primary_phone, score)

        result = _make_call(primary_phone, lead_id)

        update_lead_call_outcome(lead_id, "initiated", result["call_sid"])

        logger.info("call_lead_success lead_id={} call_sid={}", lead_id, result["call_sid"])

        return {
            "success": True,
            "call_sid": result["call_sid"],
            "status": result["status"],
            "phone": primary_phone,
            "lead_id": lead_id,
            "first_name": first_name,
        }

    except Exception as e:
        _release_call_slot(lead_id)
        logger.exception("call_lead_failed lead_id={} error={}", lead_id, str(e))

        try:
            update_lead_call_outcome(lead_id, "failed", "")
        except Exception:
            pass

        return {"success": False, "reason": "signalwire_error", "error": str(e)}


def build_voicemail_laml(lead: dict, prop: dict, language: str = "en") -> str:
    first_name = _get_first_name(lead, prop)
    address = prop.get("address", "your property")
    agent_phone = os.environ.get("SIGNALWIRE_PHONE", "")

    if language == "es":
        voice = _VM_VOICE_ES
        rate = _VM_RATE_ES
        say_text = (
            f"Oye {first_name}, te habla Sophia de San Joaquin House Buyers "
            f"sobre tu propiedad en {address}. Quiero hacerte una oferta en efectivo. "
            f"Sin reparaciones, sin agentes, y cierre rapido. "
            f"Llamame o mandame mensaje al {agent_phone}. Gracias."
        )
    else:
        voice = _VM_VOICE_EN
        rate = _VM_RATE_EN
        say_text = (
            f"Hey {first_name}, this is Sophia with San Joaquin House Buyers "
            f"calling about your property on {address}. "
            f"We'd love to make you a cash offer. No repairs, no agents, fast close. "
            f"Give me a call or text back at {agent_phone}. Talk soon."
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="{voice}" rate="{rate}">
        {say_text}
    </Say>
    <Hangup/>
</Response>"""


def build_outbound_answer_laml(lead_id: str) -> str:
    railway_url = _get_public_base_url()
    stream_url = f"{railway_url}/api/voice/outbound-stream/{lead_id}"
    ws_url = _to_ws_url(stream_url)

    logger.info("build_outbound_answer_laml lead_id={} ws_url={}", lead_id, ws_url)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream
            url="{ws_url}"
            track="both_tracks"
        />
    </Connect>
</Response>"""
