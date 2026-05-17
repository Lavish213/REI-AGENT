from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger


if not os.environ.get("RAILWAY_ENVIRONMENT"):
    load_dotenv(override=False)


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

from backend.voice.outbound_webhook import (
    router as outbound_router,
)

from backend.voice.webhook import (
    router as voice_router,
)


def _run_outbound_campaign() -> None:
    try:
        from scripts.run_outbound import run_campaign

        run_campaign()

        logger.info(
            "outbound_campaign completed"
        )

    except Exception as e:
        logger.exception(
            "outbound_campaign_error error={}",
            str(e),
        )


def _refresh_engagement() -> None:
    try:
        from backend.scout.engagement import (
            refresh_all_engagement,
        )

        refresh_all_engagement()

        logger.info(
            "engagement_refresh completed"
        )

    except Exception as e:
        logger.exception(
            "engagement_refresh_error error={}",
            str(e),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("REI Agent API starting")

    logger.info(
        "business={}",
        os.environ.get(
            "BUSINESS_NAME",
            "unknown",
        ),
    )

    logger.info(
        "agent={}",
        os.environ.get(
            "AGENT_NAME",
            "unknown",
        ),
    )

    app.state.backchannel_clips = {}
    app.state.filler_clips = {}

    app.state.call_contexts = {}
    app.state.call_started_at = {}
    app.state.call_metrics = {}

    logger.info(
        "voice startup baseline mode active"
    )

    from apscheduler.schedulers.background import (
        BackgroundScheduler,
    )

    from backend.alerts.drip import (
        start_drip_scheduler,
        stop_drip_scheduler,
    )

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

    outbound_scheduler.start()

    logger.info(
        "scheduler_started outbound=9am,1pm engagement=6am"
    )

    yield

    logger.info(
        "REI Agent API shutting down"
    )

    try:
        stop_drip_scheduler()

    except Exception as e:
        logger.warning(
            "stop_drip_scheduler_failed error={}",
            str(e),
        )

    try:
        stop_appointment_scheduler()

    except Exception as e:
        logger.warning(
            "stop_appointment_scheduler_failed error={}",
            str(e),
        )

    try:
        outbound_scheduler.shutdown(wait=False)

    except Exception as e:
        logger.warning(
            "scheduler_shutdown_failed error={}",
            str(e),
        )


app = FastAPI(
    title="REI Agent API",
    description=(
        "San Joaquin House Buyers "
        "Autonomous REI System"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    health.router,
    prefix="/api",
    tags=["health"],
)

app.include_router(
    properties.router,
    prefix="/api",
    tags=["properties"],
)

app.include_router(
    leads.router,
    prefix="/api",
    tags=["leads"],
)

app.include_router(
    calls.router,
    prefix="/api",
    tags=["calls"],
)

app.include_router(
    sms.router,
    prefix="/api",
    tags=["sms"],
)

app.include_router(
    evals.router,
    prefix="/api",
    tags=["evals"],
)

app.include_router(
    analytics.router,
    prefix="/api",
    tags=["analytics"],
)

app.include_router(
    workflow.router,
    prefix="/api",
    tags=["workflow"],
)

app.include_router(
    offers.router,
    prefix="/api",
    tags=["offers"],
)

app.include_router(
    live.router,
    prefix="/api",
    tags=["live"],
)

app.include_router(
    voice_router,
    prefix="/api",
    tags=["voice"],
)

app.include_router(
    outbound_router,
    prefix="/api",
    tags=["outbound"],
)


@app.websocket("/voice/stream/{call_sid}")
async def voice_stream(
    websocket: WebSocket,
    call_sid: str,
):
    await websocket.accept()

    import asyncio as _asyncio

    _deadline = 2.0
    _waited = 0.0
    while _waited < _deadline:
        contexts = getattr(app.state, "call_contexts", {})
        if call_sid in contexts:
            break
        await _asyncio.sleep(0.1)
        _waited += 0.1
    else:
        logger.warning(
            "voice_stream_preload_timeout call_sid={} waited={}s",
            call_sid,
            _deadline,
        )

    contexts = getattr(
        app.state,
        "call_contexts",
        {},
    )

    call_context = contexts.get(
        call_sid,
        {
            "property_context_str": (
                "No property context available. "
                "Greet naturally and determine "
                "why the caller is reaching out."
            ),
            "owner_first_name": "there",
            "lead": None,
            "boss_mode": False,
        },
    )

    app.state.call_started_at[
        call_sid
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    app.state.call_contexts[
        call_sid
    ] = call_context

    app.state.call_metrics[
        call_sid
    ] = None

    startup_clips = {
        "backchannel": getattr(
            app.state,
            "backchannel_clips",
            {},
        ),
        "filler": getattr(
            app.state,
            "filler_clips",
            {},
        ),
    }

    logger.info(
        "voice_websocket_connected "
        "call_sid={} "
        "boss_mode={}",
        call_sid,
        call_context.get(
            "boss_mode",
            False,
        ),
    )

    try:
        from backend.voice.agent import (
            run_sophia_agent,
        )

        await run_sophia_agent(
            websocket=websocket,
            call_sid=call_sid,
            call_context=call_context,
            startup_clips=startup_clips,
            metrics_store=app.state.call_metrics,
        )

    except Exception as e:
        logger.exception(
            "voice_websocket_error "
            "call_sid={} "
            "error={}",
            call_sid,
            str(e),
        )

    finally:
        getattr(
            app.state,
            "call_contexts",
            {},
        ).pop(call_sid, None)

        getattr(
            app.state,
            "call_started_at",
            {},
        ).pop(call_sid, None)

        getattr(
            app.state,
            "call_metrics",
            {},
        ).pop(call_sid, None)

        logger.info(
            "voice_websocket_cleanup "
            "call_sid={}",
            call_sid,
        )

        try:
            await websocket.close()

        except Exception:
            pass


@app.get("/")
async def root():
    return {
        "system": "REI Agent",
        "business": os.environ.get(
            "BUSINESS_NAME"
        ),
        "agent": os.environ.get(
            "AGENT_NAME"
        ),
        "status": "operational",
    }