from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.api.routes import (
    analytics,
    calls,
    evals,
    health,
    leads,
    live,
    offers,
    properties,
    sms,
    workflow,
)
from backend.voice.outbound_webhook import router as outbound_router
from backend.api.routes.sms_status import router as sms_status_router
from backend.voice.inbound_webhook import router as inbound_router


def _run_outbound_campaign() -> None:
    try:
        from scripts.run_outbound import run_campaign
        run_campaign()
        logger.info("outbound_campaign completed")
    except Exception as e:
        logger.exception("outbound_campaign_error error={}", str(e))


def _refresh_engagement() -> None:
    try:
        from backend.scout.engagement import refresh_all_engagement
        refresh_all_engagement()
        logger.info("engagement_refresh completed")
    except Exception as e:
        logger.exception("engagement_refresh_error error={}", str(e))


def _run_pending_followups() -> None:
    try:
        from backend.lib.db import get_pending_followups
        from backend.voice.outbound import call_lead
        followups = get_pending_followups(limit=5)
        for f in followups:
            lead_id = f.get("lead_id")
            if lead_id:
                result = call_lead(lead_id, bypass_cooldown=False)
                logger.info("followup_call lead_id={} success={}", lead_id, result.get("success"))
    except Exception as e:
        logger.exception("followup_poller error={}", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("REI Agent API starting")

    if os.environ.get("GROQ_API_KEY", "").strip():
        logger.critical(
            "GROQ_API_KEY is set — tools (book_appointment, end_call, transfer_call) "
            "will NOT work. Unset GROQ_API_KEY to restore full functionality."
        )

    baseline = os.environ.get("VOICE_BASELINE_MODE", "false").lower() == "true"
    if baseline:
        logger.info("voice startup baseline mode active")

    from apscheduler.schedulers.background import BackgroundScheduler
    from backend.alerts.drip import start_drip_scheduler, stop_drip_scheduler
    from backend.voice.appointment_scheduler import (
        start_appointment_scheduler,
        stop_appointment_scheduler,
    )

    start_drip_scheduler()
    start_appointment_scheduler()

    outbound_scheduler = BackgroundScheduler(
        timezone="America/Los_Angeles"
    )

    outbound_scheduler.add_job(
        _run_outbound_campaign,
        "cron",
        hour="9,13",
        minute="0",
        id="outbound_campaign",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.add_job(
        _refresh_engagement,
        "cron",
        hour="6",
        minute="0",
        id="engagement_refresh",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.add_job(
        _run_pending_followups,
        "interval",
        minutes=30,
        id="followup_poller",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.start()

    logger.info("scheduler_started outbound=9am,1pm engagement=6am followups=every30min")

    yield

    logger.info("REI Agent API shutting down")

    try:
        stop_drip_scheduler()
    except Exception as e:
        logger.warning("stop_drip_scheduler_failed error={}", str(e))

    try:
        stop_appointment_scheduler()
    except Exception as e:
        logger.warning("stop_appointment_scheduler_failed error={}", str(e))

    try:
        outbound_scheduler.shutdown(wait=False)
    except Exception as e:
        logger.warning("scheduler_shutdown_failed error={}", str(e))


app = FastAPI(
    title="REI Agent API",
    description="San Joaquin House Buyers Voice Agent Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics.router, prefix="/api")
app.include_router(calls.router, prefix="/api")
app.include_router(evals.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(live.router, prefix="/api")
app.include_router(offers.router, prefix="/api")
app.include_router(properties.router, prefix="/api")
app.include_router(sms.router, prefix="/api")
app.include_router(workflow.router, prefix="/api")
app.include_router(outbound_router, prefix="/api")
app.include_router(sms_status_router, prefix="/api")
app.include_router(inbound_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
