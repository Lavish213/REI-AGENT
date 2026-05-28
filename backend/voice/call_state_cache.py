from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

_TTL_SECONDS = 900
_REDIS_URL = os.environ.get("REDIS_URL", "")


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning("call_state_cache redis unavailable error={}", str(e))
        return None


def save_snapshot(call_sid: str, call_ctx: Any) -> None:
    client = _get_redis()
    if not client:
        return
    try:
        snapshot = {
            "emotional_state": getattr(call_ctx, "emotional_state", "NEUTRAL"),
            "trust_score": getattr(call_ctx, "trust_score", 5.0),
            "deal_heat": getattr(call_ctx, "deal_heat", 0.0),
            "objective": getattr(call_ctx, "objective", "GET_MOTIVATION"),
            "turn_count": getattr(call_ctx, "turn_count", 0),
            "disposition": getattr(call_ctx, "disposition", None),
            "situation_label": getattr(call_ctx, "situation_label", "unknown"),
            "seller_energy": getattr(call_ctx, "seller_energy", "calm"),
            "address_known": getattr(call_ctx, "address_known", False),
            "intent_locked": getattr(call_ctx, "intent_locked", False),
            "resistance_level": getattr(call_ctx, "resistance_level", "NONE"),
            "motivation_signals": getattr(call_ctx, "motivation_signals", []),
            "objections_raised": getattr(call_ctx, "objections_raised", []),
            "timeline_mentioned": getattr(call_ctx, "timeline_mentioned", None),
            "last_price_mentioned": getattr(call_ctx, "last_price_mentioned", None),
        }
        key = f"call_snapshot:{call_sid}"
        client.setex(key, _TTL_SECONDS, json.dumps(snapshot))
        logger.debug("call_state_cache saved call_sid={}", call_sid)
    except Exception as e:
        logger.warning("call_state_cache save failed call_sid={} error={}", call_sid, str(e))


def load_snapshot(call_sid: str) -> dict | None:
    client = _get_redis()
    if not client:
        return None
    try:
        key = f"call_snapshot:{call_sid}"
        raw = client.get(key)
        if raw:
            logger.info("call_state_cache restored call_sid={}", call_sid)
            return json.loads(raw)
    except Exception as e:
        logger.warning("call_state_cache load failed call_sid={} error={}", call_sid, str(e))
    return None


def delete_snapshot(call_sid: str) -> None:
    client = _get_redis()
    if not client:
        return
    try:
        client.delete(f"call_snapshot:{call_sid}")
    except Exception:
        pass
