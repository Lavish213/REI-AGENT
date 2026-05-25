from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def call_created(
    call_sid: str,
    call_context: dict[str, Any],
) -> dict[str, Any]:
    lead = call_context.get("lead") or {}
    return {
        "call_sid": call_sid,
        "direction": "outbound" if call_context.get("is_outbound") else "inbound",
        "lead_id": lead.get("id"),
        "lead_name": lead.get("owner_first_name"),
        "phone": lead.get("phone"),
        "address": call_context.get("address"),
        "situation_label": call_context.get("situation_label"),
        "boss_mode": bool(call_context.get("boss_mode")),
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def call_completed(
    call_sid: str,
    disposition: str | None,
    turn_count: int,
    transcript_length: int,
) -> dict[str, Any]:
    return {
        "call_sid": call_sid,
        "disposition": disposition,
        "turn_count": turn_count,
        "transcript_length": transcript_length,
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def turn_completed(
    call_sid: str,
    speaker: str,
    text: str,
    trust_score: float | None = None,
    deal_heat: float | None = None,
    turn_index: int = 0,
) -> dict[str, Any]:
    return {
        "call_sid": call_sid,
        "speaker": speaker,
        "text": text,
        "trust_score": trust_score,
        "deal_heat": deal_heat,
        "turn_index": turn_index,
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def transcript_completed(
    call_sid: str,
    call_id_db: str | None,
    lead_id: str | None,
    chunk_count: int,
) -> dict[str, Any]:
    return {
        "call_sid": call_sid,
        "call_id_db": call_id_db,
        "lead_id": lead_id,
        "chunk_count": chunk_count,
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def call_ended(call_sid: str) -> dict[str, Any]:
    return {
        "call_sid": call_sid,
        "occurred_at": datetime.now(UTC).isoformat(),
    }