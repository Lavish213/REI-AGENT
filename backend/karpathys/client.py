from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit
from typing import Any

import httpx
from loguru import logger

_KARPATHYS_URL = os.environ.get("KARPATHYS_URL", "").rstrip("/")
_KARPATHYS_SECRET = os.environ.get("KARPATHYS_WEBHOOK_SECRET", "")
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_MAX_RETRIES = 2


async def post_event(endpoint: str, payload: dict[str, Any]) -> bool:
    if not _KARPATHYS_URL:
        logger.debug("karpathys url not set skipping event={}", endpoint)
        return False

    allowed = {"call", "turn", "complete", "ended", "transcript", "failed", "sophia/disposition-action"}
    base = urlsplit(_KARPATHYS_URL)
    if endpoint not in allowed or not _KARPATHYS_SECRET or base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password or base.query or base.fragment or base.path not in {"", "/"}:
        return False
    route = "/api/v1/sophia/disposition-action" if endpoint == "sophia/disposition-action" else f"/api/v1/ingest/{endpoint}"
    url = f"{_KARPATHYS_URL}{route}"
    headers = {
        "Content-Type": "application/json",
        "X-Karpathys-Secret": _KARPATHYS_SECRET,
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                res = await client.post(url, json=payload, headers=headers)
                if 200 <= res.status_code < 300:
                    data = res.json()
                    if isinstance(data, dict) and data.get("persisted") is True and type(data.get("schema_version")) is int and data["schema_version"] == 1 and isinstance(data.get("receipt_id"), str) and data["receipt_id"] and data.get("call_sid") == payload.get("call_sid"):
                        logger.debug("karpathys event persisted endpoint={} status={}", endpoint, res.status_code)
                        return True
                logger.warning(
                    "karpathys event failed endpoint={} status={} attempt={}",
                    endpoint, res.status_code, attempt,
                )
        except httpx.TimeoutException:
            logger.warning("karpathys timeout endpoint={} attempt={}", endpoint, attempt)
        except Exception as error:
            logger.exception("karpathys error endpoint={} error={}", endpoint, str(error))

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)

    return False
