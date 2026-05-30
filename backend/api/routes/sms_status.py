from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response
from loguru import logger

router = APIRouter()

_DEAD_CODES = {"30003", "30006", "30007", "30008", "30009"}


@router.post("/voice/sms-status")
async def sms_status_callback(request: Request) -> Response:
    form = await request.form()
    message_sid = str(form.get("MessageSid", ""))
    status = str(form.get("MessageStatus", ""))
    to_number = str(form.get("To", ""))
    error_code = str(form.get("ErrorCode", "") or "")

    logger.info("sms_status sid={} status={} to={} error={}", message_sid, status, to_number, error_code)
    now = datetime.now(timezone.utc).isoformat()

    try:
        from backend.lib.db import _get_client
        client = _get_client()
        client.table("sms_messages").update({
            "delivery_status": status,
            "error_code": error_code or None,
            "updated_at": now,
        }).eq("signalwire_message_id", message_sid).execute()

        if status in ("failed", "undelivered") and error_code in _DEAD_CODES:
            resp = client.table("leads").select("id").eq("owner_phone", to_number).limit(1).execute()
            if resp.data:
                lead_id = resp.data[0]["id"]
                client.table("leads").update({
                    "phone_invalid": True,
                    "callable": False,
                    "updated_at": now,
                }).eq("id", lead_id).execute()
                logger.info("phone_flagged_invalid lead_id={} number={}", lead_id, to_number)
    except Exception as e:
        logger.error("sms_status_update failed sid={} error={}", message_sid, str(e))

    return Response(status_code=204)
