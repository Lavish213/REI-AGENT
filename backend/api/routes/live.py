"""
Live call state API.

Exposes active call sessions from app.state.call_contexts so operators
can see who Sophia is talking to right now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


def _sanitize_call_context(
    call_sid: str,
    ctx: dict,
    started_at: str | None,
    runtime_ctx=None,
) -> dict:
    prop = (ctx.get("property") or {}) if not ctx.get("boss_mode") else {}
    lead = ctx.get("lead") or {}
    result = {
        "call_sid": call_sid,
        "started_at": started_at,
        "boss_mode": bool(ctx.get("boss_mode")),
        "owner_first_name": ctx.get("owner_first_name"),
        "address": prop.get("address"),
        "city": prop.get("city"),
        "lead_id": lead.get("id"),
        "lead_stage": lead.get("stage"),
        "spanish": bool(ctx.get("spanish_detected", False)),
    }

    # Runtime metrics overlay (G23) — from live CallContext
    if runtime_ctx is not None:
        result["metrics"] = {
            "phase": getattr(runtime_ctx, "current_phase", None),
            "seller_energy": getattr(runtime_ctx, "seller_energy", None),
            "situation_label": getattr(runtime_ctx, "situation_label", None),
            "turn_count": getattr(runtime_ctx, "turn_count", 0),
            "disposition": getattr(runtime_ctx, "disposition", None),
            "current_emotion": getattr(runtime_ctx, "current_emotion", None),
            "motivation_signals": getattr(runtime_ctx, "motivation_signals", [])[-3:],
            "objections_raised": getattr(runtime_ctx, "objections_raised", [])[-2:],
            "timeline_mentioned": getattr(runtime_ctx, "timeline_mentioned", None),
        }

    return result


@router.get("/live/calls")
async def get_live_calls(request: Request) -> dict[str, Any]:
    call_contexts: dict = getattr(request.app.state, "call_contexts", {})
    call_started_at: dict = getattr(request.app.state, "call_started_at", {})
    call_metrics: dict = getattr(request.app.state, "call_metrics", {})

    now = datetime.now(timezone.utc).isoformat()
    calls = [
        _sanitize_call_context(sid, ctx, call_started_at.get(sid), call_metrics.get(sid))
        for sid, ctx in call_contexts.items()
    ]

    return {
        "active_count": len(calls),
        "calls": calls,
        "as_of": now,
    }


@router.get("/live/calls/{call_sid}")
async def get_live_call(call_sid: str, request: Request) -> dict[str, Any]:
    call_contexts: dict = getattr(request.app.state, "call_contexts", {})
    call_started_at: dict = getattr(request.app.state, "call_started_at", {})
    call_metrics: dict = getattr(request.app.state, "call_metrics", {})

    ctx = call_contexts.get(call_sid)
    if ctx is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Call not active")

    return _sanitize_call_context(call_sid, ctx, call_started_at.get(call_sid), call_metrics.get(call_sid))


@router.get("/live/status")
async def get_live_status(request: Request) -> dict[str, Any]:
    call_contexts: dict = getattr(request.app.state, "call_contexts", {})
    return {
        "active_calls": len(call_contexts),
        "status": "operational",
    }
