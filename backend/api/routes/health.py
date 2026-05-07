import os
import httpx
from fastapi import APIRouter
from loguru import logger

router = APIRouter()


async def _check_deepgram(key: str) -> dict:
    if not key:
        return {"status": "missing"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            auth_resp = await client.get(
                "https://api.deepgram.com/v1/auth/token",
                headers={"Authorization": f"Token {key}"},
            )
        if auth_resp.status_code == 200:
            data = auth_resp.json()
            account_status = data.get("member", {}).get("status", "unknown")
            logger.info("deepgram auth ok account_status={}", account_status)
            result = {"status": "ok", "account_status": account_status}
        elif auth_resp.status_code == 401:
            logger.error("deepgram key invalid or expired status=401")
            result = {"status": "error", "reason": "invalid_key"}
        elif auth_resp.status_code == 402:
            logger.error("deepgram account payment required status=402")
            result = {"status": "error", "reason": "payment_required"}
        else:
            logger.error(
                "deepgram auth unexpected status={} body={}",
                auth_resp.status_code,
                auth_resp.text[:100],
            )
            result = {"status": "error", "reason": f"http_{auth_resp.status_code}"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            models_resp = await client.get(
                "https://api.deepgram.com/v1/models",
                headers={"Authorization": f"Token {key}"},
            )
        if models_resp.status_code == 200:
            models_data = models_resp.json()
            stt_names = [m.get("name") for m in models_data.get("stt", [])]
            nova3_ok = "nova-3" in stt_names
            nova2_ok = "nova-2" in stt_names
            result["nova-3"] = "available" if nova3_ok else "unavailable"
            result["nova-2"] = "available" if nova2_ok else "unavailable"
            logger.info(
                "deepgram models nova-3={} nova-2={}",
                result["nova-3"],
                result["nova-2"],
            )
        return result
    except Exception as e:
        logger.error("deepgram health check error={}", str(e))
        return {"status": "error", "reason": str(e)[:80]}


@router.get("/health")
async def health_check():
    checks = {}

    try:
        from backend.lib.db import _get_client
        client = _get_client()
        client.table("properties").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception as e:
        checks["supabase"] = f"error: {str(e)[:50]}"

    try:
        sw_token = os.environ.get("SIGNALWIRE_TOKEN", "")
        checks["signalwire"] = "configured" if sw_token else "missing"
    except Exception as e:
        checks["signalwire"] = f"error: {str(e)[:50]}"

    try:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        checks["anthropic"] = "configured" if anthropic_key else "missing"
    except Exception as e:
        checks["anthropic"] = f"error: {str(e)[:50]}"

    try:
        deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "")
        checks["deepgram"] = await _check_deepgram(deepgram_key)
    except Exception as e:
        checks["deepgram"] = f"error: {str(e)[:50]}"

    try:
        cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
        checks["cartesia"] = "configured" if cartesia_key else "missing"
    except Exception as e:
        checks["cartesia"] = f"error: {str(e)[:50]}"

    def _is_ok(v) -> bool:
        if isinstance(v, dict):
            return v.get("status") in ("ok", "configured")
        return v in ("ok", "configured")

    all_ok = all(_is_ok(v) for v in checks.values())

    logger.info("health check status={} checks={}", "ok" if all_ok else "degraded", checks)

    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "agent": os.environ.get("AGENT_FULL_NAME", "Sophia Reyes"),
        "business": os.environ.get("BUSINESS_NAME", "San Joaquin House Buyers"),
    }
