from __future__ import annotations
import os
import hashlib
from datetime import datetime, timezone
from loguru import logger


def get_pool_numbers() -> list[str]:
    raw = os.environ.get("SIGNALWIRE_PHONE_POOL", "")
    if not raw:
        single = os.environ.get("SIGNALWIRE_PHONE", "")
        return [single] if single else []
    return [n.strip() for n in raw.split(",") if n.strip()]


def pick_number_for_lead(lead_id: str) -> str:
    group_id = os.environ.get("SIGNALWIRE_NUMBER_GROUP_ID", "")
    if group_id:
        return f"group:{group_id}"
    pool = get_pool_numbers()
    if not pool:
        return os.environ.get("SIGNALWIRE_PHONE", "")
    index = int(hashlib.md5(lead_id.encode()).hexdigest(), 16) % len(pool)
    return pool[index]


def mark_number_failed(phone_number: str) -> None:
    try:
        from backend.lib.db import _get_client
        _get_client().table("phone_pool_health").upsert({
            "phone_number": phone_number,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_count": 1,
        }, on_conflict="phone_number").execute()
        logger.warning("phone_pool number_marked_failed number={}", phone_number)
    except Exception as e:
        logger.error("phone_pool mark_failed error={}", str(e))


def get_healthy_pool() -> list[str]:
    pool = get_pool_numbers()
    if not pool:
        return [os.environ.get("SIGNALWIRE_PHONE", "")]
    try:
        from backend.lib.db import _get_client
        resp = (
            _get_client()
            .table("phone_pool_health")
            .select("phone_number")
            .gte("failure_count", 5)
            .execute()
        )
        dead = {r["phone_number"] for r in (resp.data or [])}
        healthy = [n for n in pool if n not in dead]
        return healthy if healthy else pool
    except Exception:
        return pool
