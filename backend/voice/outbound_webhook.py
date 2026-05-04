import os
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from backend.lib.db import get_lead_with_property, update_lead_call_outcome, insert_call
from backend.voice.outbound import build_voicemail_laml, build_outbound_answer_laml, _get_first_name

router = APIRouter()


@router.post("/voice/outbound-webhook/{lead_id}")
async def handle_outbound_answered(request: Request, lead_id: str) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid", "")
    answered_by = form.get("AnsweredBy", "")
    call_status = form.get("CallStatus", "")

    logger.info("outbound_webhook lead_id={} sid={} answered_by={} status={}", lead_id, call_sid, answered_by, call_status)

    if call_status in ("no-answer", "busy", "failed", "canceled"):
        await run_in_threadpool(update_lead_call_outcome, lead_id, call_status, call_sid)
        return PlainTextResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="text/xml",
        )

    lead = await run_in_threadpool(get_lead_with_property, lead_id)
    if not lead:
        logger.error("outbound_webhook lead_not_found lead_id={}", lead_id)
        return PlainTextResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="text/xml",
        )

    prop = lead.get("properties") or {}

    if answered_by in ("machine_end_beep", "machine_end_silence", "machine_end_other", "machine_start"):
        logger.info("outbound_voicemail lead_id={} answered_by={}", lead_id, answered_by)
        await run_in_threadpool(update_lead_call_outcome, lead_id, "voicemail", call_sid)
        laml = build_voicemail_laml(lead, prop)
        return PlainTextResponse(content=laml, media_type="text/xml")

    laml = build_outbound_answer_laml(lead_id)
    logger.info("outbound_answered lead_id={} connecting_stream", lead_id)
    return PlainTextResponse(content=laml, media_type="text/xml")


@router.post("/voice/outbound-status/{lead_id}")
async def handle_outbound_status(request: Request, lead_id: str) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", "0") or 0)

    logger.info("outbound_status lead_id={} sid={} status={} duration={}s", lead_id, call_sid, call_status, duration)

    if call_status in ("completed", "failed", "busy", "no-answer", "canceled"):
        outcome_map = {
            "completed": "answered",
            "no-answer": "no_answer",
            "busy": "busy",
            "failed": "failed",
            "canceled": "canceled",
        }
        outcome = outcome_map.get(call_status, call_status)
        await run_in_threadpool(update_lead_call_outcome, lead_id, outcome, call_sid, duration)

        if call_status == "completed" and duration > 10:
            call_data = {
                "lead_id": lead_id,
                "signalwire_call_id": call_sid,
                "direction": "outbound",
                "duration_seconds": duration,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await run_in_threadpool(insert_call, call_data)

    return PlainTextResponse(content="ok")


@router.websocket("/voice/outbound-stream/{lead_id}")
async def outbound_voice_stream(websocket: WebSocket, lead_id: str):
    await websocket.accept()

    lead = await asyncio.to_thread(get_lead_with_property, lead_id)
    prop = lead.get("properties") or {} if lead else {}

    first_name = _get_first_name(lead, prop) if lead else "there"
    address = prop.get("address", "your property") if prop else "your property"

    outbound_context = {
        "boss_mode": False,
        "is_outbound": True,
        "lead": lead,
        "lead_id": lead_id,
        "owner_first_name": first_name,
        "property_context_str": _build_outbound_context(lead, prop, first_name, address),
        "spanish_detected": False,
    }

    call_sid = f"outbound_{lead_id}"

    try:
        from backend.voice.agent import run_sophia_agent
        await run_sophia_agent(websocket, call_sid, outbound_context)
    except Exception as e:
        logger.error("outbound_stream error lead_id={} error={}", lead_id, str(e))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _build_outbound_context(lead: dict | None, prop: dict | None, first_name: str, address: str) -> str:
    if not lead or not prop:
        return (
            f"OUTBOUND CALL CONTEXT\n"
            f"You called this person. Introduce yourself warmly.\n"
            f"Greet as: Hey [name]! This is Sophia from San Joaquin House Buyers..."
        )

    score = prop.get("distress_score", 0)
    distress = (prop.get("distress_type") or "unknown").replace("_", " ").title()
    arv = prop.get("estimated_arv")
    mao = prop.get("mao")
    arv_str = f"${arv / 100:,.0f}" if arv else "unknown"
    mao_str = f"${mao / 100:,.0f}" if mao else "unknown"

    return f"""OUTBOUND CALL CONTEXT
=====================
YOU CALLED THEM. You initiated this call. Start with:
"Hey {first_name}! This is Sophia calling from San Joaquin House Buyers.
I'm reaching out about your property at {address} — do you have just a couple minutes to chat?"

If Spanish speaker detected switch immediately:
"Oye {first_name}! Habla Sophia de San Joaquin House Buyers.
Te llamo sobre tu propiedad en {address}. ¿Tienes unos minutos?"

Owner: {first_name}
Address: {address} {prop.get("city", "")}
Distress Type: {distress}
Score: {score}/100
ARV: {arv_str}
MAO: {mao_str}

OUTBOUND CALL GUIDANCE
======================
They did NOT call you — they may be surprised or guarded.
Extra important: react before you respond, go slower, be warmer.
Goal: get them talking about the property situation.
Close for a walkthrough or callback if they engage.
If voicemail, leave one message max — do not leave multiple."""
