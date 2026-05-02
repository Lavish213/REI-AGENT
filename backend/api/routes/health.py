import os
from fastapi import APIRouter
from loguru import logger

router = APIRouter()


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
        checks["deepgram"] = "configured" if deepgram_key else "missing"
    except Exception as e:
        checks["deepgram"] = f"error: {str(e)[:50]}"

    try:
        cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
        checks["cartesia"] = "configured" if cartesia_key else "missing"
    except Exception as e:
        checks["cartesia"] = f"error: {str(e)[:50]}"

    all_ok = all(v == "ok" or v == "configured" for v in checks.values())

    logger.info("health check status={} checks={}", "ok" if all_ok else "degraded", checks)

    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "agent": os.environ.get("AGENT_FULL_NAME", "Sophia Reyes"),
        "business": os.environ.get("BUSINESS_NAME", "San Joaquin House Buyers"),
    }
