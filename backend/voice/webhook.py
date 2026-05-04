import os
import asyncio
import json
from datetime import datetime, timezone
from loguru import logger
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool

from backend.lib.db import insert_call, update_lead_stage


router = APIRouter()


async def _preload_and_store(app, call_sid: str, caller_phone: str) -> None:
    try:
        from backend.voice.preloader import preload_call_context
        context = await run_in_threadpool(preload_call_context, caller_phone)
        app.state.call_contexts = getattr(app.state, "call_contexts", {})
        app.state.call_contexts[call_sid] = context
        logger.info("preload complete call_sid={} phone={}", call_sid, caller_phone)
    except Exception as e:
        logger.error("preload failed call_sid={} error={}", call_sid, str(e))
        app.state.call_contexts = getattr(app.state, "call_contexts", {})
        app.state.call_contexts[call_sid] = {
            "property_context_str": "No property context available. Greet warmly and ask if they are calling about selling their home.",
            "owner_first_name": "there",
            "lead": None,
        }


@router.post("/voice/inbound")
async def handle_inbound_call(request: Request) -> Response:
    form = await request.form()
    caller_phone = form.get("From", "")
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")

    logger.info("inbound call from={} sid={} status={}", caller_phone, call_sid, call_status)

    ws_url = os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("PUBLIC_URL", "")
    ws_url = ws_url.replace("https://", "wss://").replace("http://", "ws://")

    laml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}/voice/stream/{call_sid}" />
    </Connect>
</Response>"""

    asyncio.create_task(_preload_and_store(request.app, call_sid, caller_phone))

    logger.info("returning LaML for call sid={}", call_sid)
    return PlainTextResponse(content=laml, media_type="text/xml")


@router.post("/voice/status")
async def handle_call_status(request: Request) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    duration = form.get("CallDuration", "0")

    logger.info("call status sid={} status={} duration={}s", call_sid, call_status, duration)

    if call_status in ("completed", "failed", "busy", "no-answer"):
        contexts = getattr(request.app.state, "call_contexts", {})
        contexts.pop(call_sid, None)

    return PlainTextResponse(content="ok")


@router.post("/voice/inbound-sms")
async def handle_inbound_sms(request: Request) -> Response:
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "").strip()
    message_sid = form.get("MessageSid", "")

    logger.info("inbound SMS from={} body={} sid={}", from_number, body[:50], message_sid)

    opt_out_keywords = {"stop", "unsubscribe", "cancel", "quit", "end"}
    if body.lower() in opt_out_keywords:
        logger.info("opt-out received from={}", from_number)
        from backend.lib.db import insert_sms
        insert_sms({
            "direction": "inbound",
            "body": body,
            "signalwire_message_id": message_sid,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>You have been unsubscribed. Reply START to resubscribe.</Message>
</Response>"""
        return PlainTextResponse(content=twiml, media_type="text/xml")

    from backend.lib.db import insert_sms
    insert_sms({
        "direction": "inbound",
        "body": body,
        "signalwire_message_id": message_sid,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })

    return PlainTextResponse(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response/>", media_type="text/xml")
