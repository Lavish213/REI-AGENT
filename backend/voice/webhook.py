from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from loguru import logger


router = APIRouter()


def _normalize_phone(phone: str) -> str:
    digits = "".join(char for char in phone if char.isdigit())

    if len(digits) >= 10:
        return digits[-10:]

    return digits


def _is_boss(caller_phone: str) -> bool:
    owner_phone = os.environ.get("OWNER_PHONE", "")

    if not owner_phone:
        return False

    return (
        _normalize_phone(caller_phone)
        == _normalize_phone(owner_phone)
    )


def _build_ws_url() -> str:
    base_url = (
        os.environ.get("RAILWAY_STATIC_URL")
        or os.environ.get("PUBLIC_URL", "")
    ).strip()

    if not base_url:
        raise RuntimeError(
            "PUBLIC_URL or RAILWAY_STATIC_URL missing"
        )

    return (
        base_url
        .replace("https://", "wss://")
        .replace("http://", "ws://")
        .rstrip("/")
    )


def _empty_twiml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response/>"
    )


async def _preload_and_store(
    app,
    call_sid: str,
    caller_phone: str,
) -> None:
    try:
        from backend.voice.preloader import (
            preload_boss_context,
            preload_call_context,
        )

        boss_mode = _is_boss(caller_phone)

        if boss_mode:
            context = await run_in_threadpool(
                preload_boss_context
            )

        else:
            context = await run_in_threadpool(
                preload_call_context,
                caller_phone,
            )

        context["boss_mode"] = boss_mode

        if not hasattr(app.state, "call_contexts"):
            app.state.call_contexts = {}

        app.state.call_contexts[call_sid] = context

        logger.info(
            "voice_preload_complete "
            "call_sid={} "
            "phone={} "
            "boss_mode={}",
            call_sid,
            caller_phone,
            boss_mode,
        )

    except Exception as e:
        logger.exception(
            "voice_preload_failed "
            "call_sid={} "
            "error={}",
            call_sid,
            str(e),
        )

        if not hasattr(app.state, "call_contexts"):
            app.state.call_contexts = {}

        app.state.call_contexts[call_sid] = {
            "boss_mode": False,
            "lead": None,
            "address": "",
            "owner_first_name": "there",
            "property_context_str": (
                "No property context available. "
                "Greet naturally and determine why "
                "the caller is reaching out."
            ),
        }


@router.post("/voice/inbound")
async def handle_inbound_call(
    request: Request,
) -> Response:
    try:
        form = await request.form()

        caller_phone = str(form.get("From", "")).strip()
        call_sid = str(form.get("CallSid", "")).strip()
        call_status = str(
            form.get("CallStatus", "")
        ).strip()

        logger.info(
            "voice_inbound_received "
            "from={} "
            "call_sid={} "
            "status={}",
            caller_phone,
            call_sid,
            call_status,
        )

        ws_url = _build_ws_url()

        laml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream
            url="{ws_url}/api/voice/stream/{call_sid}"
            track="inbound_track"
        />
    </Connect>
</Response>"""

        asyncio.create_task(
            _preload_and_store(
                request.app,
                call_sid,
                caller_phone,
            )
        )

        logger.info(
            "voice_stream_initialized "
            "call_sid={} "
            "ws_url={}",
            call_sid,
            ws_url,
        )

        return PlainTextResponse(
            content=laml,
            media_type="text/xml",
        )

    except Exception as e:
        logger.exception(
            "voice_inbound_failed error={}",
            str(e),
        )

        return PlainTextResponse(
            content=_empty_twiml(),
            media_type="text/xml",
            status_code=500,
        )




@router.websocket("/voice/stream/{call_sid}")
async def inbound_voice_stream(websocket: WebSocket, call_sid: str):
    from backend.voice.agent import run_sophia_agent
    app = websocket.app
    call_context = {}
    store = getattr(app.state, "call_context_store", {})
    if call_sid in store:
        call_context = store.pop(call_sid)
    await run_sophia_agent(
        websocket=websocket,
        call_sid=call_sid,
        call_context=call_context,
        metrics_store=getattr(app.state, "metrics_store", None),
    )

@router.post("/voice/status")
async def handle_call_status(
    request: Request,
) -> Response:
    try:
        form = await request.form()

        call_sid = str(form.get("CallSid", "")).strip()

        call_status = str(
            form.get("CallStatus", "")
        ).strip()

        duration = str(
            form.get("CallDuration", "0")
        ).strip()

        logger.info(
            "voice_status_update "
            "call_sid={} "
            "status={} "
            "duration={}s",
            call_sid,
            call_status,
            duration,
        )

        if call_status in {
            "completed",
            "failed",
            "busy",
            "no-answer",
            "canceled",
        }:
            contexts = getattr(
                request.app.state,
                "call_contexts",
                {},
            )

            removed = contexts.pop(call_sid, None)

            logger.info(
                "voice_context_cleanup "
                "call_sid={} "
                "removed={}",
                call_sid,
                bool(removed),
            )

        return PlainTextResponse(
            content="ok",
        )

    except Exception as e:
        logger.exception(
            "voice_status_failed error={}",
            str(e),
        )

        return PlainTextResponse(
            content="error",
            status_code=500,
        )


@router.post("/voice/inbound-sms")
async def handle_inbound_sms(
    request: Request,
) -> Response:
    try:
        form = await request.form()

        from_number = str(
            form.get("From", "")
        ).strip()

        body = str(
            form.get("Body", "")
        ).strip()

        message_sid = str(
            form.get("MessageSid", "")
        ).strip()

        logger.info(
            "voice_inbound_sms "
            "from={} "
            "message_sid={}",
            from_number,
            message_sid,
        )

        owner_phone = os.environ.get("OWNER_PHONE", "")
        if owner_phone and "".join(c for c in from_number if c.isdigit())[-10:] == "".join(c for c in owner_phone if c.isdigit())[-10:]:
            try:
                from backend.lib.db import _get_client
                client = _get_client()
                pending = client.table("operator_queries").select("id").eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                if pending.data:
                    query_id = pending.data[0]["id"]
                    client.table("operator_queries").update({"answer": body, "status": "answered"}).eq("id", query_id).execute()
                    logger.info("operator_reply recorded query_id={}", query_id)
                    return PlainTextResponse(content=_empty_twiml(), media_type="text/xml")
            except Exception as op_err:
                logger.warning("operator_reply failed error={}", str(op_err))

        from backend.alerts.drip import (
            handle_inbound_reply,
        )

        action = await asyncio.to_thread(
            handle_inbound_reply,
            from_number,
            body,
            message_sid,
        )

        logger.info(
            "voice_inbound_sms_processed "
            "from={} "
            "action={}",
            from_number,
            action,
        )

        if action == "opted_out":
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>
        You have been unsubscribed.
        Reply START to resubscribe.
    </Message>
</Response>"""

            return PlainTextResponse(
                content=twiml,
                media_type="text/xml",
            )

        return PlainTextResponse(
            content=_empty_twiml(),
            media_type="text/xml",
        )

    except Exception as e:
        logger.exception(
            "voice_inbound_sms_failed error={}",
            str(e),
        )

        return PlainTextResponse(
            content=_empty_twiml(),
            media_type="text/xml",
            status_code=500,
        )