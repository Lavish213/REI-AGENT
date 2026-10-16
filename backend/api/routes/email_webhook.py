from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import HTMLResponse
from loguru import logger

router = APIRouter()

def _verify_signature(request_body: bytes, signature: str, timestamp: str) -> bool:
    try:
        import base64
        import time
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        public_key = os.environ.get("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
        if not public_key or not signature or abs(time.time() - int(timestamp)) > 300:
            return False
        key = serialization.load_der_public_key(base64.b64decode(public_key))
        key.verify(base64.b64decode(signature), timestamp.encode() + request_body, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


@router.post("/email/webhook")
async def sendgrid_webhook(request: Request) -> Response:
    body = await request.body()
    if len(body) > 2_000_000:
        return Response(status_code=413)
    sig = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
    ts  = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")
    if not _verify_signature(body, sig, ts):
        logger.warning("sendgrid_webhook invalid signature")
        return Response(status_code=403)

    try:
        import json
        events = json.loads(body)
    except Exception as e:
        logger.error("sendgrid_webhook json parse failed error={}", str(e))
        return Response(status_code=400)

    import asyncio
    from backend.alerts.delivery import accept_events
    try:
        await asyncio.to_thread(accept_events, 'email', events if isinstance(events, list) else [events])
    except (ValueError, TypeError):
        return Response(status_code=422)
    except Exception as error:
        logger.warning('email_events_not_saved type={}', type(error).__name__)
        return Response(status_code=503)
    return Response(status_code=200)


def _handle_unsubscribe(lead_id: str, email: str, method: str = "email_link") -> None:
    from backend.lib.db import suppress_email_address
    suppress_email_address(email)
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


@router.post("/email/inbound")
async def inbound_email(request: Request):
    import asyncio
    from fastapi import HTTPException
    from backend.alerts.inbound_email import verify_adapter, accept_reply
    if len(os.environ.get("INBOUND_EMAIL_ADAPTER_SECRET", "")) < 32:
        raise HTTPException(503, "Verified inbound provider adapter is not configured")
    body = await request.body()
    if not verify_adapter(body, request.headers.get("X-Email-Timestamp", ""), request.headers.get("X-Email-Signature", "")):
        raise HTTPException(403, "Invalid inbound provider authentication")
    try:
        payload = await request.json()
        return await asyncio.to_thread(accept_reply, payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(503, "Reply was not durably accepted") from error
