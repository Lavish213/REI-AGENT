import os
import httpx
from fastapi import APIRouter
from loguru import logger

router = APIRouter()


@router.get("/health/dashboard-delivery")
async def dashboard_delivery_health():
    import asyncio
    from backend.karpathys.client import delivery_target
    from backend.lib.db import dashboard_event_journal_health
    if delivery_target() is None:
        return {"status": "disabled"}
    try:
        result = await asyncio.to_thread(dashboard_event_journal_health)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(503, "Dashboard delivery journal unavailable")
    return {"status": "degraded" if result["dead"] or result["oldest_pending_seconds"] > 300 else "ok", **result}


@router.post("/health/dashboard-delivery/{event_id}/retry")
async def dashboard_delivery_retry(event_id: str):
    import asyncio
    from uuid import UUID
    from fastapi import HTTPException
    from backend.karpathys.client import delivery_target
    from backend.lib.db import retry_dashboard_event
    try:
        UUID(event_id)
    except ValueError:
        raise HTTPException(422, "Invalid event identifier")
    target = delivery_target()
    if target is None or not await asyncio.to_thread(retry_dashboard_event, event_id, target):
        raise HTTPException(409, "Event cannot be retried for the configured destination")
    return {"status": "queued", "event_id": event_id}


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


@router.get("/health/workflow-recovery")
async def workflow_recovery_health():
    import asyncio
    from fastapi import HTTPException
    from backend.lib.db import workflow_journal_health
    try:
        result = await asyncio.to_thread(workflow_journal_health)
    except Exception as error:
        raise HTTPException(503, "Workflow journal unavailable") from error
    return {"status": "degraded" if result["requires_review"] or result["oldest_due_seconds"] > 300 or not result["review_owner_configured"] else "ok", **result}


@router.get("/health/workflow-recovery/review")
async def workflow_review():
    import asyncio
    from backend.lib.db import workflow_review_queue
    return {'items': await asyncio.to_thread(workflow_review_queue)}


@router.post("/health/workflow-recovery/{identity}/reconcile")
async def workflow_reconcile(identity: str, body: dict):
    import asyncio
    from fastapi import HTTPException
    from backend.lib.db import reconcile_workflow_job
    try:
        return await asyncio.to_thread(reconcile_workflow_job, identity, body['decision'], body['actor_id'], body['reason'])
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, 'Explicit operator reconciliation required') from error
