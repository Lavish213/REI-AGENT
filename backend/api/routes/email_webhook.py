from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import HTMLResponse
from loguru import logger

router = APIRouter()

_WEBHOOK_SECRET = os.environ.get("SENDGRID_WEBHOOK_SECRET", "")


def _verify_signature(request_body: bytes, signature: str, timestamp: str) -> bool:
    if not _WEBHOOK_SECRET:
        return True
    try:
        import hmac
        import hashlib
        payload = timestamp.encode() + request_body
        expected = hmac.new(_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return True


@router.post("/email/webhook")
async def sendgrid_webhook(request: Request) -> Response:
    body = await request.body()
    sig = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
    ts  = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")
    if sig and ts and not _verify_signature(body, sig, ts):
        logger.warning("sendgrid_webhook invalid signature")
        return Response(status_code=403)

    try:
        import json
        events = json.loads(body)
    except Exception as e:
        logger.error("sendgrid_webhook json parse failed error={}", str(e))
        return Response(status_code=400)

    for event in (events if isinstance(events, list) else [events]):
        try:
            await _process_event(event)
        except Exception as e:
            logger.error("sendgrid_webhook event error event={} error={}", event.get("event"), str(e))

    return Response(status_code=200)


async def _process_event(event: dict) -> None:
    event_type     = event.get("event", "")
    email          = event.get("email", "")
    sg_message_id  = event.get("sg_message_id", "")
    lead_id        = event.get("lead_id") or (event.get("custom_args") or {}).get("lead_id", "")
    timestamp      = event.get("timestamp", 0)
    occurred_at    = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else datetime.now(timezone.utc).isoformat()

    if not lead_id and email:
        lead_id = _lookup_lead_by_email(email) or ""

    _log_email_event(lead_id or None, email, sg_message_id, event_type, event, occurred_at)

    if event_type == "delivered":
        _update_delivery_status(sg_message_id, "delivered", lead_id)

    elif event_type == "bounce":
        bounce_type = event.get("type", "bounce")
        _update_delivery_status(sg_message_id, f"bounced_{bounce_type}", lead_id)
        if bounce_type in ("bounce", "blocked"):
            _handle_hard_bounce(lead_id, email, bounce_type)

    elif event_type == "spamreport":
        _handle_spam_report(lead_id, email)

    elif event_type == "unsubscribe":
        _handle_unsubscribe(lead_id, email, method="sendgrid_unsubscribe")

    elif event_type == "open":
        _handle_open(lead_id, sg_message_id)

    elif event_type == "click":
        _handle_click(lead_id, sg_message_id, event.get("url", ""))

    elif event_type in ("deferred", "dropped"):
        _update_delivery_status(sg_message_id, event_type, lead_id)


def _lookup_lead_by_email(email: str) -> str | None:
    try:
        from backend.lib.db import _get_client
        resp = _get_client().table("leads").select("id").eq("owner_email", email).limit(1).execute()
        return resp.data[0]["id"] if resp.data else None
    except Exception:
        return None


def _log_email_event(lead_id, email, sg_message_id, event_type, payload, occurred_at) -> None:
    try:
        from backend.lib.db import _get_client
        _get_client().table("email_events").insert({
            "lead_id": lead_id,
            "email": email,
            "sg_message_id": sg_message_id,
            "event_type": event_type,
            "payload": payload,
            "occurred_at": occurred_at,
        }).execute()
    except Exception as e:
        logger.error("email_event log failed type={} error={}", event_type, str(e))


def _update_delivery_status(sg_message_id: str, status: str, lead_id: str) -> None:
    if not sg_message_id:
        return
    try:
        from backend.lib.db import _get_client
        _get_client().table("email_sends").update({
            "delivery_status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("sg_message_id", sg_message_id).execute()
    except Exception as e:
        logger.warning("email_sends status update failed sg={} error={}", sg_message_id, str(e))


def _handle_hard_bounce(lead_id: str, email: str, reason: str) -> None:
    try:
        from backend.lib.db import _get_client
        client = _get_client()
        lid = lead_id
        if not lid:
            resp = client.table("leads").select("id").eq("owner_email", email).limit(1).execute()
            lid = resp.data[0]["id"] if resp.data else None
        if lid:
            client.table("leads").update({
                "email_bounced": True,
                "email_bounce_reason": reason,
                "email_paused": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", lid).execute()
    except Exception as e:
        logger.error("handle_hard_bounce failed lead_id={} error={}", lead_id, str(e))


def _handle_spam_report(lead_id: str, email: str) -> None:
    try:
        from backend.lib.db import _get_client, pause_lead_email, pause_lead_drip
        from backend.compliance.compliance import ComplianceEngine
        client = _get_client()
        if not lead_id:
            resp = client.table("leads").select("id").eq("owner_email", email).limit(1).execute()
            lead_id = resp.data[0]["id"] if resp.data else ""
        if lead_id:
            pause_lead_email(lead_id)
            pause_lead_drip(lead_id)
            ComplianceEngine().handle_opt_out(lead_id, method="spam_report", trigger_word="spam")
    except Exception as e:
        logger.error("handle_spam_report failed lead_id={} error={}", lead_id, str(e))


def _handle_unsubscribe(lead_id: str, email: str, method: str = "email_link") -> None:
    try:
        from backend.lib.db import _get_client, pause_lead_email
        client = _get_client()
        if not lead_id:
            resp = client.table("leads").select("id").eq("owner_email", email).limit(1).execute()
            lead_id = resp.data[0]["id"] if resp.data else ""
        if lead_id:
            pause_lead_email(lead_id)
            client.table("leads").update({
                "opted_out": True,
                "opted_out_sms": True,
                "opted_out_at": datetime.now(timezone.utc).isoformat(),
                "opted_out_method": method,
            }).eq("id", lead_id).execute()
    except Exception as e:
        logger.error("handle_unsubscribe failed lead_id={} error={}", lead_id, str(e))


def _handle_open(lead_id: str, sg_message_id: str) -> None:
    if not lead_id:
        return
    try:
        from backend.lib.db import update_engagement_score, _get_client
        update_engagement_score(lead_id, "sms_opened")
        _get_client().table("email_sends").update({
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "delivery_status": "opened",
        }).eq("sg_message_id", sg_message_id).execute()
    except Exception as e:
        logger.warning("handle_open failed lead_id={} error={}", lead_id, str(e))


def _handle_click(lead_id: str, sg_message_id: str, url: str) -> None:
    if not lead_id:
        return
    try:
        from backend.lib.db import update_engagement_score, _get_client
        update_engagement_score(lead_id, "sms_reply")
        _get_client().table("email_sends").update({
            "clicked_at": datetime.now(timezone.utc).isoformat(),
            "clicked_url": url[:500],
            "delivery_status": "clicked",
        }).eq("sg_message_id", sg_message_id).execute()
    except Exception as e:
        logger.warning("handle_click failed lead_id={} error={}", lead_id, str(e))


@router.get("/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(token: str = Query(...)) -> str:
    from backend.alerts.email import verify_unsubscribe_token
    result = verify_unsubscribe_token(token)
    if not result:
        return _unsubscribe_html("Invalid or expired link.", success=False)
    lead_id, email = result
    _handle_unsubscribe(lead_id, email, method="email_link_click")
    logger.info("email_unsubscribe_link lead_id={} email={}", lead_id, email)
    return _unsubscribe_html("You've been unsubscribed successfully.", success=True)


def _unsubscribe_html(message: str, success: bool) -> str:
    color = "#2d7a4f" if success else "#c0392b"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe</title>
<style>body{{margin:0;padding:40px 20px;background:#f5f4f0;font-family:-apple-system,sans-serif;text-align:center;}}
.card{{max-width:420px;margin:0 auto;background:#fff;border-radius:8px;padding:40px;border:1px solid #e0dfd8;}}
h1{{font-size:20px;color:{color};margin:0 0 12px;font-weight:600;}}
p{{color:#888882;font-size:14px;margin:0;}}</style>
</head><body>
<div class="card">
  <h1>{message}</h1>
  <p>San Joaquin House Buyers · Stockton, CA</p>
</div>
</body></html>"""
