from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
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
from backend.api.routes.intel import router as intel_router
from backend.api.routes.email_webhook import router as email_webhook_router
from backend.voice.webhook import router as inbound_router


def _run_daily_drip_triggers() -> None:
    try:
        from backend.alerts.drip import run_daily_drip_triggers
        run_daily_drip_triggers()
    except Exception as e:
        logger.exception("run_daily_drip_triggers failed error={}", str(e))


def _run_scout() -> None:
    try:
        from backend.scout.cron import run_scout_cycle
        run_scout_cycle()
        logger.info("scout_run completed")
    except Exception as e:
        logger.exception("scout_run failed error={}", str(e))


def _run_sophia_loop() -> None:
    try:
        from backend.alerts.sophia_loop import run_sophia_loop
        results = run_sophia_loop()
        logger.info("sophia_loop completed results={}", results)
    except Exception as e:
        logger.exception("sophia_loop_error error={}", str(e))


def _run_outbound_campaign() -> None:
    try:
        from backend.voice.campaign import run_campaign
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
    from backend.lib.db import claim_due_call_followups, claim_due_callbacks, finish_followup_claim, finish_callback_claim, campaign_is_running
    from backend.voice.outbound import call_lead
    try:
        if not campaign_is_running():
            return
        try:
            followups = claim_due_call_followups()
        except Exception as error:
            logger.exception("followup_claim failed error={}", str(error))
            followups = []
        for followup in followups:
            if not followup.get("claim_token"):
                logger.error("followup_claim missing ownership id={}", followup.get("id"))
                continue
            success = False
            try:
                success = bool(call_lead(followup["lead_id"], bypass_cooldown=False).get("success"))
            except Exception as error:
                logger.exception("followup_attempt failed id={} error={}", followup.get("id"), str(error))
            finally:
                try:
                    finish_followup_claim(followup["id"], success, followup.get("claim_token"))
                except Exception as error:
                    logger.exception("followup_completion failed id={} error={}", followup.get("id"), str(error))
        try:
            callbacks = claim_due_callbacks()
        except Exception as error:
            logger.exception("callback_claim failed error={}", str(error))
            callbacks = []
        for callback in callbacks:
            if not callback.get("callback_claim_token"):
                logger.error("callback_claim missing ownership id={}", callback.get("id"))
                continue
            success = False
            try:
                success = bool(call_lead(callback["id"], bypass_cooldown=True).get("success"))
            except Exception as error:
                logger.exception("callback_attempt failed id={} error={}", callback.get("id"), str(error))
            finally:
                try:
                    finish_callback_claim(callback["id"], callback["callback_scheduled_at"], success, callback.get("callback_claim_token"))
                except Exception as error:
                    logger.exception("callback_completion failed id={} error={}", callback.get("id"), str(error))
    except Exception as error:
        logger.exception("followup_poller error={}", str(error))


def _flush_bob_facts():
    try:
        from backend.lib.db import flush_bob_call_fact_outbox
        result = flush_bob_call_fact_outbox()
        if result["failed"] or result["expired"]:
            logger.warning("bob_fact_recovery results={}", result)
    except Exception as error:
        logger.error("bob_fact_recovery_failed type={}", type(error).__name__)


@asynccontextmanager
async def _application_lifespan(app: FastAPI):
    logger.info("REI Agent API starting")
    if os.environ.get("ENABLE_BACKGROUND_JOBS", "false").lower() != "true":
        yield
        return
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

    try:
        from backend.lib.db import warm_database
        warm_database()
        logger.info("supabase_warmup complete")
    except Exception as error:
        logger.warning("supabase_warmup failed error={}", str(error))

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

    outbound_scheduler.add_job(
        _run_sophia_loop,
        "cron",
        hour="10,14,18",
        minute="0",
        id="sophia_loop",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.add_job(
        _run_daily_drip_triggers,
        "cron",
        hour="8",
        minute="30",
        id="daily_drip_triggers",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.add_job(
        _run_scout,
        "cron",
        hour="7,12,17",
        minute="0",
        id="scout_run",
        replace_existing=True,
        max_instances=1,
    )

    outbound_scheduler.start()

    logger.info("scheduler_started sophia_loop=10am,2pm,6pm outbound=9am,1pm engagement=6am followups=every30min daily_drip=8:30am")

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


async def _bob_fact_recovery_loop():
    import asyncio
    while True:
        await asyncio.to_thread(_flush_bob_facts)
        await asyncio.sleep(30)


async def _suppression_recovery_loop():
    import asyncio
    from backend.lib import db
    while True:
        try:
            result = await asyncio.to_thread(db.recover_contact_suppressions)
            if result["retrying"] or result["unowned"]:
                logger.warning("suppression_recovery_degraded results={}", result)
        except Exception as error:
            logger.error("suppression_recovery_failed type={}", type(error).__name__)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from backend.lib import db
    from backend.karpathys.outbox import start_recovery
    suppression = None
    delivery = None
    recovery = None
    provider_events = None
    try:
        if os.environ.get("CONTACT_SUPPRESSION_PATH") or os.environ.get("OUTBOUND_ENABLED", "false").lower() == "true":
            await asyncio.to_thread(db.suppression_journal_health)
            suppression = asyncio.create_task(_suppression_recovery_loop())
        from backend.alerts.delivery import recover_loop
        await asyncio.to_thread(db.delivery_event_health)
        provider_events = asyncio.create_task(recover_loop())
        delivery = await start_recovery()
        recovery = asyncio.create_task(_bob_fact_recovery_loop()) if os.environ.get("VOICE_FACT_OUTBOX_PATH") else None
        async with _application_lifespan(app):
            yield
    finally:
        if provider_events:
            provider_events.cancel()
            await asyncio.gather(provider_events, return_exceptions=True)
        if suppression:
            suppression.cancel()
            await asyncio.gather(suppression, return_exceptions=True)
        if recovery:
            recovery.cancel()
            await asyncio.gather(recovery, return_exceptions=True)
        if delivery:
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)


app = FastAPI(
    title="REI Agent API",
    description="San Joaquin House Buyers Voice Agent Platform",
    version="1.0.0",
    lifespan=lifespan,
)
from backend.api.security import OperatorAuthentication
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(OperatorAuthentication)
origins = [origin.strip() for origin in os.environ.get("DASHBOARD_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])




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
app.include_router(intel_router, prefix="/api")
app.include_router(email_webhook_router, prefix="/api")
app.include_router(inbound_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}

from backend.api.routes.appointments import router as appointments_router
app.include_router(appointments_router, prefix="/api")

from backend.api.routes.bob import router as bob_router
app.include_router(bob_router, prefix="/api")
