from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from loguru import logger

from backend.lib.db import (
    get_lead_with_property,
    insert_call,
    update_lead_call_outcome,
)

from backend.lib.osm import (
    geocode_address,
    get_nearby_landmarks,
)

from backend.voice.outbound import (
    _get_first_name,
    build_outbound_answer_laml,
    build_voicemail_laml,
)


router = APIRouter()


_EMPTY_RESPONSE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Hangup/></Response>"
)

_VM_DEFINITE = {
    "machine_end_beep",
    "machine_end_silence",
}

_VM_UNCERTAIN = {
    "machine_start",
    "machine_end_other",
}

_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "busy",
    "no-answer",
    "canceled",
}


@router.post("/voice/outbound-webhook/{lead_id}")
async def handle_outbound_answered(
    request: Request,
    lead_id: str,
) -> Response:
    try:
        form = await request.form()

        call_sid = str(form.get("CallSid", "")).strip()
        answered_by = str(form.get("AnsweredBy", "")).strip()
        call_status = str(form.get("CallStatus", "")).strip()

        logger.info(
            "outbound_webhook lead_id={} call_sid={} answered_by={} status={}",
            lead_id, call_sid, answered_by, call_status,
        )

        if call_status in _TERMINAL_STATUSES - {"completed"}:
            await run_in_threadpool(update_lead_call_outcome, lead_id, call_status, call_sid)
            return PlainTextResponse(content=_EMPTY_RESPONSE, media_type="text/xml")

        lead = await run_in_threadpool(get_lead_with_property, lead_id)

        if not lead:
            logger.error("outbound_lead_not_found lead_id={}", lead_id)
            return PlainTextResponse(content=_EMPTY_RESPONSE, media_type="text/xml")

        prop = lead.get("properties") or {}

        if answered_by in _VM_DEFINITE:
            logger.info("outbound_voicemail_detected lead_id={} answered_by={}", lead_id, answered_by)
            await run_in_threadpool(update_lead_call_outcome, lead_id, "voicemail", call_sid)
            laml = await _build_voicemail_response(lead, prop)
            return PlainTextResponse(content=laml, media_type="text/xml")

        if answered_by in _VM_UNCERTAIN:
            logger.info("outbound_amd_uncertain_connecting lead_id={} answered_by={}", lead_id, answered_by)

        laml = build_outbound_answer_laml(lead_id)
        logger.info("outbound_answered_connecting_stream lead_id={}", lead_id)
        return PlainTextResponse(content=laml, media_type="text/xml")

    except Exception as e:
        logger.exception("outbound_webhook_failed lead_id={} error={}", lead_id, str(e))
        return PlainTextResponse(content=_EMPTY_RESPONSE, media_type="text/xml", status_code=500)


@router.post("/voice/outbound-status/{lead_id}")
async def handle_outbound_status(
    request: Request,
    lead_id: str,
) -> Response:
    try:
        form = await request.form()

        call_sid = str(form.get("CallSid", "")).strip()
        call_status = str(form.get("CallStatus", "")).strip()
        duration = int(form.get("CallDuration", "0") or 0)

        logger.info(
            "outbound_status lead_id={} call_sid={} status={} duration={}s",
            lead_id, call_sid, call_status, duration,
        )

        if call_status in _TERMINAL_STATUSES:
            outcome_map = {
                "completed": "answered",
                "no-answer": "no_answer",
                "busy": "busy",
                "failed": "failed",
                "canceled": "canceled",
            }

            outcome = outcome_map.get(call_status, call_status)

            await run_in_threadpool(update_lead_call_outcome, lead_id, outcome, call_sid, duration)

            try:
                from backend.voice.outbound import _release_call_slot, _schedule_retry_for_disposition
                _release_call_slot(lead_id)
                if call_status in ("no-answer", "busy", "voicemail"):
                    attempt = int(form.get("attempt_count", 0) or 0)
                    _schedule_retry_for_disposition(lead_id, call_status, attempt)
            except Exception as slot_err:
                logger.warning("release_slot_failed lead_id={} error={}", lead_id, str(slot_err))

            answered_by_status = str(form.get("AnsweredBy", "")).strip()
            if call_status == "completed" and duration < 60 and answered_by_status not in ("human", "human-residence", "human-business"):
                logger.info("short_call_auto_dead lead_id={} duration={}s answered_by={}", lead_id, duration, answered_by_status)
                await run_in_threadpool(update_lead_call_outcome, lead_id, "dead", call_sid, duration)

        return PlainTextResponse(content="ok")

    except Exception as e:
        logger.exception("outbound_status_failed lead_id={} error={}", lead_id, str(e))
        return PlainTextResponse(content="error", status_code=500)


@router.websocket("/voice/outbound-stream/{lead_id}")
async def outbound_voice_stream(
    websocket: WebSocket,
    lead_id: str,
):
    await websocket.accept()

    try:
        lead = await asyncio.to_thread(get_lead_with_property, lead_id)
        prop = (lead.get("properties") or {}) if lead else {}
        first_name = _get_first_name(lead, prop) if lead else "there"
        address = prop.get("address", "your property") if prop else "your property"
        landmark = await _get_landmark_for_property(prop) if prop else None

        from backend.qa.transcript_intel import build_prior_call_context
        prior_context = build_prior_call_context(lead) if lead else None

        base_context_str = _build_outbound_context(lead, prop, first_name, address, landmark)

        if prior_context:
            base_context_str = f"{base_context_str}\n\n{prior_context}"

        preloaded_packet = None
        try:
            from backend.lib.intel_assembler import assemble_intel_packet
            import asyncio as _asyncio
            preloaded_packet = await _asyncio.wait_for(
                _asyncio.to_thread(assemble_intel_packet, lead_id),
                timeout=4.0,
            )
            logger.info("intel_preloaded lead_id={} state={}", lead_id, preloaded_packet.get("packet_state", "unknown"))
        except Exception as _intel_err:
            logger.warning("intel_preload_failed lead_id={} error={}", lead_id, str(_intel_err))

        from backend.voice.preloader import _detect_situation, _get_initial_trust
        situation_label = _detect_situation(lead) if lead else "unknown"
        initial_trust = _get_initial_trust(lead) if lead else 5.0
        preloaded_packet = None
        try:
            from backend.lib.intel_assembler import assemble_intel_packet
            import asyncio as _ai
            preloaded_packet = await _ai.wait_for(_ai.to_thread(assemble_intel_packet, lead_id), timeout=5.0)
            logger.info("intel_preloaded lead_id={} state={}", lead_id, preloaded_packet.get("packet_state", "unknown"))
        except Exception as _ie:
            logger.warning("intel_preload_failed lead_id={} error={}", lead_id, str(_ie))
        outbound_context = {
            "boss_mode": False,
            "is_outbound": True,
            "lead": lead,
            "lead_id": lead_id,
            "owner_first_name": first_name,
            "address": address,
            "property_context_str": base_context_str,
            "spanish_detected": False,
            "preloaded_intel_packet": preloaded_packet,
        }

        call_sid = f"outbound_{lead_id}"
        try:
            import json as _json
            for _ in range(5):
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
                msg = _json.loads(raw)
                if msg.get("event") == "start":
                    real_sid = (
                        msg.get("start", {}).get("callSid")
                        or msg.get("callSid")
                        or ""
                    )
                    if real_sid:
                        call_sid = real_sid
                    break
        except Exception as _sid_err:
            logger.warning("outbound_stream_sid_fallback lead_id={} error={}", lead_id, str(_sid_err))

        logger.info("outbound_stream_started lead_id={} call_sid={}", lead_id, call_sid)

        app_state = websocket.app.state
        if not hasattr(app_state, "call_metrics"):
            app_state.call_metrics = {}
        if not hasattr(app_state, "call_started_at"):
            app_state.call_started_at = {}
        from datetime import datetime, timezone as _tz
        app_state.call_started_at[call_sid] = datetime.now(_tz.utc).isoformat()
        from backend.voice.agent import run_sophia_agent
        await run_sophia_agent(websocket=websocket, call_sid=call_sid, call_context=outbound_context, metrics_store=app_state.call_metrics)
        app_state.call_metrics.pop(call_sid, None)
        app_state.call_started_at.pop(call_sid, None)

    except Exception as e:
        logger.exception("outbound_stream_failed lead_id={} error={}", lead_id, str(e))

    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _build_voicemail_response(lead: dict, prop: dict) -> str:
    try:
        in_stl = (
            not lead.get("speed_to_lead_completed", False)
            and (lead.get("speed_to_lead_attempts") or 0) > 0
        )

        if in_stl:
            from backend.alerts.ringless import build_ringless_voicemail_laml, select_script_number
            stl_attempts = lead.get("speed_to_lead_attempts") or 1
            script_num = select_script_number(stl_attempts)
            logger.info(
                "ringless_voicemail_selected lead_id={} script={} stl_attempts={}",
                lead.get("id"), script_num, stl_attempts,
            )
            return build_ringless_voicemail_laml(lead, prop, script_num)

        return build_voicemail_laml(lead, prop)

    except Exception as e:
        logger.exception("build_voicemail_response_failed lead_id={} error={}", lead.get("id"), str(e))
        return _EMPTY_RESPONSE


async def _get_landmark_for_property(prop: dict) -> str | None:
    try:
        address = prop.get("address", "")
        city = prop.get("city", "Stockton")

        if not address:
            return None

        geo = await asyncio.to_thread(geocode_address, address, city, "CA")

        if not geo:
            return city or None

        landmarks = await asyncio.to_thread(get_nearby_landmarks, geo["lat"], geo["lng"], 1000)

        if landmarks:
            return landmarks[0]["name"]

        return geo.get("neighborhood") or city or None

    except Exception as e:
        logger.warning("landmark_lookup_failed error={}", str(e))
        return None


def _build_outbound_context(
    lead: dict | None,
    prop: dict | None,
    first_name: str,
    address: str,
    landmark: str | None = None,
) -> str:
    if not lead or not prop:
        return (
            "You initiated this outbound call. "
            "Introduce yourself naturally as Sophia "
            "with San Joaquin House Buyers."
        )

    score = prop.get("distress_score", 0)
    distress = (prop.get("distress_type") or "unknown").replace("_", " ").title()
    arv = prop.get("estimated_arv")
    mao = prop.get("mao")
    arv_str = f"${arv:,.0f}" if arv else "unknown"
    mao_str = f"${mao:,.0f}" if mao else "unknown"
    city = prop.get("city", "Stockton")

    if landmark:
        neighborhood_line = (
            f"Nearby landmark: {landmark}\n"
            f'Use naturally: "That whole area near {landmark} has been moving really fast lately."'
        )
    else:
        neighborhood_line = (
            f'Use city hook naturally: "That whole {city} area has been really active lately."'
        )

    return f"""
OUTBOUND CALL CONTEXT
=====================

YOU initiated this call.

Owner: {first_name}
Address: {address} {city}
Distress Type: {distress}
Score: {score}/100
ARV: {arv_str}
MAO: {mao_str}

NEIGHBOURHOOD HOOK
==================

{neighborhood_line}

OUTBOUND CALL GUIDANCE
======================

They did NOT call you.

They may:
- be surprised
- guarded
- skeptical
- distracted

Go slower.
React before responding.
Sound warm and local.

Primary goal:
get them talking naturally
about the property situation.

If they engage:
move toward walkthrough or callback.

If voicemail:
leave ONE message only.
""".strip()


@router.post("/voice/recording-status/{lead_id}")
async def handle_recording_status(request: Request, lead_id: str) -> Response:
    try:
        form = await request.form()
        call_sid = str(form.get("CallSid", "")).strip()
        recording_url = str(form.get("RecordingUrl", "")).strip()
        recording_sid = str(form.get("RecordingSid", "")).strip()
        recording_duration = int(form.get("RecordingDuration", "0") or 0)
        status = str(form.get("RecordingStatus", "")).strip()

        logger.info(
            "recording_status lead_id={} call_sid={} status={} duration={}s url={}",
            lead_id, call_sid, status, recording_duration, recording_url[:60] if recording_url else "",
        )

        if recording_url and status == "completed":
            from backend.lib.db import _get_client
            try:
                _get_client().table("calls").update({
                    "recording_url": recording_url,
                    "recording_sid": recording_sid,
                    "recording_duration_seconds": recording_duration,
                }).eq("signalwire_call_id", call_sid).execute()
                logger.info("recording_saved call_sid={}", call_sid)
            except Exception as db_err:
                logger.warning("recording_save_failed call_sid={} error={}", call_sid, str(db_err))

        return Response(status_code=204)
    except Exception as e:
        logger.exception("recording_status_failed lead_id={} error={}", lead_id, str(e))
        return Response(status_code=500)
