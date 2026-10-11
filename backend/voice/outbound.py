from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import pytz
from loguru import logger

from backend.lib.db import (
    get_lead_with_property,
    update_lead_call_outcome,
)


PACIFIC = pytz.timezone("America/Los_Angeles")

NO_ANSWER_SECONDS = 35
MIN_DISTRESS_SCORE = 50
CALL_COOLDOWN_HOURS = 72

_VM_VOICE_EN = "Polly.Joanna"
_VM_RATE_EN = "95%"
_VM_VOICE_ES = "Polly.Lupe"
_VM_RATE_ES = "95%"


def _is_calling_hours() -> bool:
    now_pt = datetime.now(PACIFIC)
    start = int(os.environ.get("CALLING_HOURS_START", 9))
    end = int(os.environ.get("CALLING_HOURS_END", 21))
    return start <= now_pt.hour < end


def _get_signalwire_base() -> str:
    space = os.environ["SIGNALWIRE_SPACE"].strip()
    if not space.startswith("http"):
        space = f"https://{space}"
    return space.rstrip("/")


def _get_public_base_url() -> str:
    url = (
        os.environ.get("PUBLIC_URL")
        or os.environ.get("RAILWAY_STATIC_URL")
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
    name = (
        lead.get("first_name")
        or lead.get("owner_name")
        or (prop or {}).get("owner_name")
        or ""
    ).strip()
    parts = name.split()
    return parts[0] if parts else "there"


def _get_phone_list(prop: dict) -> list[str]:
    phones = prop.get("callable_phones")
    if not phones or not isinstance(phones, list):
        return []
    result = []
    for p in phones:
        if not p:
            continue
        raw = str(p).strip()
        digits = "".join(c for c in raw if c.isdigit())
        if raw.startswith("+"):
            result.append(raw)
        elif len(digits) == 11 and digits.startswith("1"):
            result.append("+" + digits)
        elif len(digits) == 10:
            result.append("+1" + digits)
        else:
            result.append(raw)
    return result


def _build_signalwire_auth() -> tuple[str, str]:
    return (
        os.environ["SIGNALWIRE_PROJECT_ID"],
        os.environ["SIGNALWIRE_TOKEN"],
    )


def _make_call(to_phone: str, lead_id: str) -> dict[str, str]:
    project_id = os.environ["SIGNALWIRE_PROJECT_ID"]
    try:
        from backend.alerts.phone_pool import pick_number_for_lead
        from_phone = pick_number_for_lead(lead_id)
    except Exception:
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
        "MachineDetection": "Enable",
        "MachineDetectionTimeout": "4",
        "AsyncAmd": "true",
        "AsyncAmdStatusCallback": callback_url,
        "Record": "true",
        "RecordingStatusCallback": f"{railway_url}/api/voice/recording-status/{lead_id}",
        "RecordingStatusCallbackMethod": "POST",
    }

    logger.info("signalwire_call_request lead_id={} to={} callback_url={}", lead_id, to_phone, callback_url)

    with httpx.Client() as client:
        response = client.post(url, auth=_build_signalwire_auth(), data=payload, timeout=20, headers={"Accept": "application/json"})
        response.raise_for_status()
        logger.info("signalwire_response status={} body={}", response.status_code, response.text[:200])
        import xml.etree.ElementTree as ET
        try:
            data = response.json()
            call_sid = data.get("sid", "") or data.get("call_sid", "")
            status = data.get("status", "")
        except Exception:
            try:
                root = ET.fromstring(response.text)
                call_sid = root.findtext("Sid") or ""
                status = root.findtext("Status") or "initiated"
            except Exception:
                call_sid = ""
                status = "initiated"

    return {"call_sid": call_sid, "status": status}


_MAX_CONCURRENT_CALLS = 3
_REDIS_CONCURRENT_KEY = "rei_agent:{calls}:concurrent"
_REDIS_OWNERS_KEY = "rei_agent:{calls}:owners"
_REDIS_CALLS_KEY = "rei_agent:{calls}:provider_ids"


def _get_redis_client():
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        import redis
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


_ACQUIRE_SLOT_LUA = """
local now = tonumber(ARGV[1])
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', now)
for _, lead in ipairs(expired) do
  redis.call('HDEL', KEYS[2], lead)
  redis.call('HDEL', KEYS[3], lead)
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then return 0 end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[4]), ARGV[2])
redis.call('HSET', KEYS[2], ARGV[2], ARGV[5])
redis.call('HDEL', KEYS[3], ARGV[2])
for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, tonumber(ARGV[4]) + 60) end
return 1
"""


def _acquire_call_slot(lead_id: str, attempt_token: str = "") -> bool:
    import time
    client = _get_redis_client()
    if not client:
        logger.error("call_capacity_unavailable")
        return False
    try:
        return bool(client.eval(_ACQUIRE_SLOT_LUA, 3, _REDIS_CONCURRENT_KEY, _REDIS_OWNERS_KEY, _REDIS_CALLS_KEY, time.time(), lead_id, _MAX_CONCURRENT_CALLS, 3600, attempt_token))
    except Exception as error:
        logger.warning("acquire_call_slot failed error={}", str(error))
        return False


def _bind_call_slot(lead_id: str, attempt_token: str, call_sid: str) -> bool:
    client = _get_redis_client()
    if not client or not attempt_token or not call_sid:
        return False
    script = """
    if redis.call('HGET', KEYS[2], ARGV[1]) ~= ARGV[2] then return 0 end
    if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
    redis.call('HSET', KEYS[3], ARGV[1], ARGV[3])
    local ttl = redis.call('TTL', KEYS[1])
    if ttl > 0 then redis.call('EXPIRE', KEYS[3], ttl) end
    return 1
    """
    try:
        return bool(client.eval(script, 3, _REDIS_CONCURRENT_KEY, _REDIS_OWNERS_KEY, _REDIS_CALLS_KEY, lead_id, attempt_token, call_sid))
    except Exception as error:
        logger.warning("bind_call_slot failed error={}", str(error))
        return False


def _release_call_slot(lead_id: str, attempt_token: str = "", call_sid: str = "") -> bool:
    client = _get_redis_client()
    if not client:
        return False
    script = """
    local owner = redis.call('HGET', KEYS[2], ARGV[1])
    local provider = redis.call('HGET', KEYS[3], ARGV[1])
    if ARGV[3] ~= '' then
      if provider ~= ARGV[3] then return 0 end
    elseif owner and owner ~= ARGV[2] then return 0 end
    redis.call('ZREM', KEYS[1], ARGV[1])
    redis.call('HDEL', KEYS[2], ARGV[1])
    redis.call('HDEL', KEYS[3], ARGV[1])
    return 1
    """
    try:
        return bool(client.eval(script, 3, _REDIS_CONCURRENT_KEY, _REDIS_OWNERS_KEY, _REDIS_CALLS_KEY, lead_id, attempt_token, call_sid))
    except Exception as error:
        logger.warning("release_call_slot failed error={}", str(error))
        return False


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
        from backend.lib.db import create_followup
        create_followup(
            lead_id=lead_id,
            priority="medium",
            followup_type="call",
            notes=f"Auto-retry after {disposition}. Attempt {attempt_count + 1}.",
            created_by="sophia",
            scheduled_at=(datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat(),
        )
        logger.info("retry_scheduled lead_id={} disposition={} delay_hours={:.1f}", lead_id, disposition, delay_seconds / 3600)
    except Exception as e:
        logger.warning("schedule_retry failed lead_id={} error={}", lead_id, str(e))


def _check_active_call(lead_id: str) -> bool:
    client = _get_redis_client()
    if not client:
        return False
    try:
        import time
        client.zremrangebyscore(_REDIS_CONCURRENT_KEY, "-inf", time.time())
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
    import uuid
    attempt_token = uuid.uuid4().hex
    provider_accepted = False
    from backend.voice.execution_context import outbound_enabled
    if not outbound_enabled():
        return {"success": False, "reason": "outbound_disabled"}
    try:
        from backend.lib.db import campaign_is_running
        if not campaign_is_running():
            return {"success": False, "reason": "campaign_paused"}
        from backend.compliance.compliance import ComplianceEngine
        engine = ComplianceEngine()
        result = engine.check_call_allowed(lead_id)

        if not result.allowed:
            logger.warning("outbound_compliance_blocked lead_id={} reason={}", lead_id, result.reason)
            try:
                from backend.karpathys import emitter as _ke
                import asyncio as _aio
                _aio.get_event_loop().run_until_complete(_ke.emit_call_failed(lead_id, result.reason))
            except Exception:
                pass
            return {"success": False, "reason": result.reason}

        lead = get_lead_with_property(lead_id)

        if not lead:
            logger.error("call_lead_lead_not_found lead_id={}", lead_id)
            return {"success": False, "reason": "lead_not_found"}

        prop = lead.get("properties") or {}
        if lead.get("callable") is False or lead.get("workflow_state") in ("closed", "dead_lead") or lead.get("stage") in ("closed", "dead"):
            return {"success": False, "reason": "lead_not_callable"}

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
                disposition = (lead.get("disposition") or "").upper()
                cooldown = 24 if disposition == "HOT" else 48 if disposition == "WARM" else CALL_COOLDOWN_HOURS
                if hours_since < cooldown:
                    return {"success": False, "reason": "called_recently"}

        score = int(prop.get("distress_score", 0))

        if score < MIN_DISTRESS_SCORE and not bypass_cooldown:
            return {"success": False, "reason": "score_too_low"}

        callback_at = _safe_iso_to_datetime(lead.get("callback_scheduled_at"))
        if callback_at and callback_at > datetime.now(timezone.utc):
            return {"success": False, "reason": "callback_not_due"}

        if _check_active_call(lead_id):
            return {"success": False, "reason": "call_in_progress"}

        if not _acquire_call_slot(lead_id, attempt_token):
            return {"success": False, "reason": "at_capacity"}

        first_name = _get_first_name(lead, prop)
        primary_phone = phones[0]

        logger.info("call_lead_initiating lead_id={} phone={} score={}", lead_id, primary_phone, score)

        result = _make_call(primary_phone, lead_id)

        if not result["call_sid"]:
            raise RuntimeError("Phone provider did not return a call ID")
        provider_accepted = True
        if not _bind_call_slot(lead_id, attempt_token, result["call_sid"]):
            logger.error("provider_call_slot_unbound lead_id={} call_sid={}", lead_id, result["call_sid"])
        try:
            update_lead_call_outcome(lead_id, "initiated", result["call_sid"])
        except Exception as error:
            logger.error("initiated_call_not_persisted lead_id={} error={}", lead_id, str(error))

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
        if not provider_accepted:
            _release_call_slot(lead_id, attempt_token=attempt_token)
        logger.exception("call_lead_failed lead_id={} error={}", lead_id, str(e))

        try:
            update_lead_call_outcome(lead_id, "failed", "")
        except Exception:
            pass

        try:
            from backend.karpathys import emitter as _ke
            import asyncio as _aio
            _aio.get_event_loop().run_until_complete(_ke.emit_call_failed(lead_id, "signalwire_error"))
        except Exception:
            pass
        try:
            import asyncio as _aio
            from backend.karpathys import emitter as _ke
            loop = _aio.get_event_loop()
            if loop.is_running():
                _aio.create_task(_ke.emit_call_failed(lead_id, "signalwire_error"))
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
            f"Hey {first_name} — Sophia here. "
            f"I was looking at {address} and had a quick question for you. "
            f"Call or text me back when you get a chance at {agent_phone}. Thanks."
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

    from backend.voice.session import issue_stream_token
    token = issue_stream_token("outbound:" + lead_id)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream
            url="{ws_url}"
            track="inbound_track"
        >
            <Parameter name="authorization" value="{token}"/>
        </Stream>
    </Connect>
</Response>"""
