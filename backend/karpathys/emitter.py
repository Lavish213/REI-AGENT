from __future__ import annotations

from typing import Any

from loguru import logger

from backend.karpathys.outbox import enqueue_event
from backend.karpathys import events


async def emit_call_created(call_sid: str, call_context: dict[str, Any]) -> bool:
    try:
        payload = events.call_created(call_sid, call_context)
        return await enqueue_event("call", payload)
    except Exception as error:
        logger.warning("emit_call_created failed call_sid={} type={}", call_sid, type(error).__name__)
        return False


async def emit_call_ended(call_sid: str) -> bool:
    try:
        payload = events.call_ended(call_sid)
        return await enqueue_event("ended", payload)
    except Exception as error:
        logger.warning("emit_call_ended failed call_sid={} type={}", call_sid, type(error).__name__)
        return False


async def emit_call_completed(
    call_sid: str,
    disposition: str | None,
    turn_count: int,
    transcript_length: int,
) -> bool:
    try:
        payload = events.call_completed(call_sid, disposition, turn_count, transcript_length)
        return await enqueue_event("complete", payload)
    except Exception as error:
        logger.warning("emit_call_completed failed call_sid={} type={}", call_sid, type(error).__name__)
        return False


async def emit_turn_completed(
    call_sid: str,
    speaker: str,
    text: str,
    trust_score: float | None = None,
    deal_heat: float | None = None,
    turn_index: int = 0,
) -> bool:
    try:
        payload = events.turn_completed(call_sid, speaker, text, trust_score, deal_heat, turn_index)
        return await enqueue_event("turn", payload)
    except Exception as error:
        logger.warning("emit_turn_completed failed call_sid={} type={}", call_sid, type(error).__name__)
        return False


async def emit_transcript_completed(
    call_sid: str,
    call_id_db: str | None,
    lead_id: str | None,
    chunk_count: int,
    chunks: list[dict[str, Any]] | None = None,
) -> bool:
    try:
        payload = events.transcript_completed(call_sid, call_id_db, lead_id, chunk_count, chunks)
        return await enqueue_event("transcript", payload)
    except Exception as error:
        logger.warning("emit_transcript_completed failed call_sid={} type={}", call_sid, type(error).__name__)
        return False

async def emit_call_failed(
    lead_id: str | None,
    reason: str,
    call_sid: str | None = None,
) -> bool:
    try:
        payload = events.call_failed(lead_id, reason, call_sid)
        return await enqueue_event("failed", payload)
    except Exception as error:
        logger.warning("emit_call_failed failed lead_id={} type={}", lead_id, type(error).__name__)
        return False


async def emit_disposition_action(
    call_sid: str,
    lead_id: str | None,
    disposition: str,
    full_name: str | None = None,
    phone: str | None = None,
) -> bool:
    try:
        payload = events.disposition_action(call_sid, lead_id, disposition, full_name, phone)
        return await enqueue_event("sophia/disposition-action", payload)
    except Exception as error:
        logger.warning("emit_disposition_action failed call_sid={} type={}", call_sid, type(error).__name__)
        return False
