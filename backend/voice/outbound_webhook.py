import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from backend.lib.db import get_lead_with_property, update_lead_call_outcome, insert_call
from backend.voice.outbound import build_voicemail_laml, build_outbound_answer_laml, _get_first_name
from backend.lib.osm import geocode_address, get_nearby_landmarks

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

        in_stl = (
            not lead.get("speed_to_lead_completed", False)
            and (lead.get("speed_to_lead_attempts") or 0) > 0
        )
        if in_stl:
            from backend.alerts.ringless import (
                build_ringless_voicemail_laml,
                select_script_number,
            )
            stl_attempts = lead.get("speed_to_lead_attempts") or 1
            script_num = select_script_number(stl_attempts)
            laml = build_ringless_voicemail_laml(lead, prop, script_num)
            logger.info(
                "ringless_voicemail lead_id={} script={} stl_attempts={}",
                lead_id,
                script_num,
                stl_attempts,
            )
        else:
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


async def _get_landmark_for_property(prop: dict) -> str | None:
    try:
        address = prop.get("address", "")
        city = prop.get("city", "Stockton")
        if not address:
            return None
        geo = await asyncio.to_thread(geocode_address, address, city, "CA")
        if not geo:
            return city or None
        landmarks = await asyncio.to_thread(
            get_nearby_landmarks, geo["lat"], geo["lng"], 1000
        )
        if landmarks:
            return landmarks[0]["name"]
        return geo.get("neighborhood") or city or None
    except Exception as e:
        logger.warning("landmark_lookup_failed error={}", str(e))
        return None


@router.websocket("/voice/outbound-stream/{lead_id}")
async def outbound_voice_stream(websocket: WebSocket, lead_id: str):
    await websocket.accept()

    lead = await asyncio.to_thread(get_lead_with_property, lead_id)
    prop = lead.get("properties") or {} if lead else {}

    first_name = _get_first_name(lead, prop) if lead else "there"
    address = prop.get("address", "your property") if prop else "your property"

    landmark = await _get_landmark_for_property(prop) if prop else None

    from backend.qa.transcript_intel import build_prior_call_context
    prior_context = build_prior_call_context(lead) if lead else None
    base_context_str = _build_outbound_context(lead, prop, first_name, address, landmark)
    if prior_context:
        base_context_str = base_context_str + "\n\n" + prior_context

    outbound_context = {
        "boss_mode": False,
        "is_outbound": True,
        "lead": lead,
        "lead_id": lead_id,
        "owner_first_name": first_name,
        "property_context_str": base_context_str,
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


def _build_outbound_context(
    lead: dict | None,
    prop: dict | None,
    first_name: str,
    address: str,
    landmark: str | None = None,
) -> str:
    if not lead or not prop:
        return (
            "OUTBOUND CALL CONTEXT\n"
            "You called this person. Introduce yourself warmly.\n"
            "Greet as: Hey [name]! This is Sophia from San Joaquin House Buyers..."
        )

    score = prop.get("distress_score", 0)
    distress = (prop.get("distress_type") or "unknown").replace("_", " ").title()
    arv = prop.get("estimated_arv")
    mao = prop.get("mao")
    arv_str = f"${arv / 100:,.0f}" if arv else "unknown"
    mao_str = f"${mao / 100:,.0f}" if mao else "unknown"
    city = prop.get("city", "Stockton")

    if landmark:
        neighborhood_line = (
            f"Nearby landmark for opener: {landmark}\n"
            f'Use naturally: "I was looking at your place on {address} — '
            f"that whole area near {landmark} has been moving really fast lately.\"\n"
            f'Or: "That whole {city} area near {landmark} has been really active lately."'
        )
    else:
        neighborhood_line = (
            f'Use city hook: "That whole {city} area has been really active lately."'
        )

    return f"""OUTBOUND CALL CONTEXT
=====================
YOU CALLED THEM. You initiated this call.
Use one of the 4 openers from your system prompt (A, B, C, or D). Rotate randomly.

Owner: {first_name}
Address: {address} {city}
Distress Type: {distress}
Score: {score}/100
ARV: {arv_str}
MAO: {mao_str}

NEIGHBORHOOD HOOK
=================
{neighborhood_line}

OPENER GUIDANCE
===============
After opener: drop address then STOP. Let silence work. Do not fill it.
If Spanish speaker detected switch immediately:
"Oye {first_name}! Habla Sophia de San Joaquin House Buyers.
Te llamo sobre tu propiedad en {address}. ¿Tienes unos minutos?"

OUTBOUND CALL GUIDANCE
======================
They did NOT call you — they may be surprised or guarded.
Extra important: react before you respond, go slower, be warmer.
Goal: get them talking about the property situation.
Close for a walkthrough or callback if they engage.
If voicemail, leave one message max — do not leave multiple."""
