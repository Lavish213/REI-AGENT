from __future__ import annotations

import asyncio
import os
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

    url = f"{_KARPATHYS_URL}/api/ingest/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-Karpathys-Secret": _KARPATHYS_SECRET,
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code < 300:
                    logger.debug("karpathys event sent endpoint={} status={}", endpoint, res.status_code)
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