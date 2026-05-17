import os
import asyncio
from loguru import logger
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool


router = APIRouter()


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _is_boss(caller_phone: str) -> bool:
    owner = os.environ.get("OWNER_PHONE", "")
    return bool(owner) and _normalize_phone(caller_phone) == _normalize_phone(owner)


async def _preload_and_store(app, call_sid: str, caller_phone: str) -> None:
    try:
        from backend.voice.preloader import preload_call_context, preload_boss_context
        boss_mode = _is_boss(caller_phone)
        if boss_mode:
            context = await run_in_threadpool(preload_boss_context)
        else:
            context = await run_in_threadpool(preload_call_context, caller_phone)
        context["boss_mode"] = boss_mode
        app.state.call_contexts = getattr(app.state, "call_contexts", {})
        app.state.call_contexts[call_sid] = context
        logger.info("preload complete call_sid={} phone={} boss_mode={}", call_sid, caller_phone, boss_mode)
    except Exception as e:
        logger.error("preload failed call_sid={} error={}", call_sid, str(e))
        app.state.call_contexts = getattr(app.state, "call_contexts", {})
        app.state.call_contexts[call_sid] = {
            "boss_mode": False,
            "property_context_str": "No property context available. Greet professionally and ask if they are calling about selling their property.",
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
        <Stream url="{ws_url}/voice/stream/{call_sid}" track="both_tracks" />
    </Connect>
</Response>"""

    asyncio.create_task(_preload_and_store(request.app, call_sid, caller_phone))

    logger.info("signalwire laml response: {}", laml)
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

    logger.info("inbound_sms from={} sid={}", from_number, message_sid)

    from backend.alerts.drip import handle_inbound_reply
    action = await asyncio.to_thread(handle_inbound_reply, from_number, body, message_sid)
    logger.info("inbound_sms action={} from={}", action, from_number)

    if action == "opted_out":
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>You have been unsubscribed. Reply START to resubscribe.</Message>
</Response>"""
        return PlainTextResponse(content=twiml, media_type="text/xml")

    return PlainTextResponse(
        content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="text/xml",
    )
