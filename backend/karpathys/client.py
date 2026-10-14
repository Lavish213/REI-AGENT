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


def delivery_target() -> str | None:
    import hashlib
    from uuid import UUID
    if not _KARPATHYS_URL:
        return None
    base = urlsplit(_KARPATHYS_URL)
    if not _KARPATHYS_SECRET or base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password or base.query or base.fragment or base.path not in {"", "/"}:
        raise ValueError("Invalid dashboard delivery configuration")
    if base.scheme == "http" and base.hostname not in {"localhost", "127.0.0.1", "::1"} and os.environ.get("KARPATHYS_ALLOW_INSECURE_INTERNAL_HTTP", "false").lower() != "true":
        raise ValueError("Dashboard delivery requires HTTPS")
    tenant = str(UUID(os.environ.get("TENANT_ID") or "00000000-0000-0000-0000-000000000001"))
    return hashlib.sha256((_KARPATHYS_URL + ":" + tenant).encode()).hexdigest()


async def send_event(endpoint: str, payload: dict[str, Any]) -> dict:
    if not _KARPATHYS_URL:
        logger.debug("karpathys url not set skipping event={}", endpoint)
        return {"receipt": None, "error": "transport_unavailable", "permanent": False}

    allowed = {"call", "turn", "complete", "ended", "transcript", "failed", "business", "sophia/disposition-action"}
    base = urlsplit(_KARPATHYS_URL)
    if endpoint not in allowed or not _KARPATHYS_SECRET or base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password or base.query or base.fragment or base.path not in {"", "/"}:
        return {"receipt": None, "error": "transport_unavailable", "permanent": False}
    route = "/api/v1/sophia/disposition-action" if endpoint == "sophia/disposition-action" else f"/api/v1/ingest/{endpoint}"
    url = f"{_KARPATHYS_URL}{route}"
    headers = {
        "Content-Type": "application/json",
        "X-Karpathys-Secret": _KARPATHYS_SECRET,
    }

    failure = {"receipt": None, "error": "transport_unavailable", "permanent": False}
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                res = await client.post(url, json=payload, headers=headers)
                if 200 <= res.status_code < 300:
                    data = res.json()
                    if isinstance(data, dict) and data.get("persisted") is True and type(data.get("schema_version")) is int and data["schema_version"] == 1 and isinstance(data.get("receipt_id"), str) and data["receipt_id"] and data.get("call_sid") == payload.get("call_sid"):
                        logger.debug("karpathys event persisted endpoint={} status={}", endpoint, res.status_code)
                        return {"receipt": data, "error": None, "permanent": False}
                failure = {"receipt": None, "error": "invalid_receipt" if 200 <= res.status_code < 300 else "authentication_rejected" if res.status_code in {401, 403} else "payload_rejected" if res.status_code in {400, 409, 413, 422} else "transport_unavailable", "permanent": res.status_code in {400, 409, 413, 422}}
                logger.warning(
                    "karpathys event failed endpoint={} status={} attempt={}",
                    endpoint, res.status_code, attempt,
                )
        except httpx.TimeoutException:
            logger.warning("karpathys timeout endpoint={} attempt={}", endpoint, attempt)
        except Exception as error:
            logger.warning("karpathys error endpoint={} type={}", endpoint, type(error).__name__)

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)

    return failure


async def post_event(endpoint: str, payload: dict[str, Any]) -> bool:
    return (await send_event(endpoint, payload))["receipt"] is not None
