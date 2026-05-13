import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

if not os.environ.get("RAILWAY_ENVIRONMENT"):
   load_dotenv(override=False)

from backend.api.routes import (
    health,
    properties,
    leads,
    calls,
    sms,
    evals,
    analytics,
    workflow,
    offers,
)
from backend.voice.webhook import router as voice_router
from backend.voice.outbound_webhook import router as outbound_router


def _run_outbound_campaign() -> None:
    try:
        from scripts.run_outbound import run_campaign
        run_campaign()
    except Exception as e:
        logger.error("outbound_campaign_error error={}", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("REI Agent API starting up")
    logger.info("business={}", os.environ.get("BUSINESS_NAME", "unknown"))
    logger.info("agent={}", os.environ.get("AGENT_NAME", "unknown"))

    from backend.voice.processors.backchannel import pregenerate_backchannel_clips

    app.state.backchannel_clips = {}

    try:
        app.state.backchannel_clips = await pregenerate_backchannel_clips()
        logger.info(
            "startup clips ready backchannel={}",
            len(app.state.backchannel_clips),
        )
    except Exception as e:
        logger.warning("startup clip generation failed error={} continuing anyway", str(e))

    from backend.alerts.drip import start_drip_scheduler, stop_drip_scheduler
    from backend.voice.appointment_scheduler import start_appointment_scheduler, stop_appointment_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    start_drip_scheduler()
    start_appointment_scheduler()

    outbound_scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
    outbound_scheduler.add_job(
        _run_outbound_campaign,
        "cron",
        hour="9,13",
        minute="0",
        id="outbound_campaign",
        replace_existing=True,
    )

    def _refresh_engagement() -> None:
        try:
            from backend.scout.engagement import refresh_all_engagement
            refresh_all_engagement()
        except Exception as e:
            logger.error("engagement_refresh_error error={}", str(e))

    outbound_scheduler.add_job(
        _refresh_engagement,
        "cron",
        hour="6",
        minute="0",
        id="engagement_refresh",
        replace_existing=True,
    )
    outbound_scheduler.start()
    logger.info("outbound_scheduler started cron=9am,1pm PT engagement_refresh=6am")

    yield

    stop_drip_scheduler()
    stop_appointment_scheduler()
    outbound_scheduler.shutdown(wait=False)
    logger.info("REI Agent API shutting down")


app = FastAPI(
    title="REI Agent API",
    description="San Joaquin House Buyers — Autonomous Real Estate Investment System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(properties.router, prefix="/api", tags=["properties"])
app.include_router(leads.router, prefix="/api", tags=["leads"])
app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(sms.router, prefix="/api", tags=["sms"])
app.include_router(evals.router, prefix="/api", tags=["evals"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(workflow.router, prefix="/api", tags=["workflow"])
app.include_router(offers.router, prefix="/api", tags=["offers"])
app.include_router(voice_router, prefix="/api", tags=["voice"])
app.include_router(outbound_router, prefix="/api", tags=["outbound"])


@app.websocket("/voice/stream/{call_sid}")
async def voice_stream(websocket: WebSocket, call_sid: str):
    await websocket.accept()

    contexts = getattr(app.state, "call_contexts", {})
    call_context = contexts.get(call_sid, {
        "property_context_str": "No property context available. Greet warmly and ask if they are calling about selling their home.",
        "owner_first_name": "there",
        "lead": None,
    })

    startup_clips = {
        "backchannel": getattr(app.state, "backchannel_clips", {}),
    }

    try:
        from backend.voice.agent import run_sophia_agent
        await run_sophia_agent(websocket, call_sid, call_context, startup_clips=startup_clips)
    except Exception as e:
        logger.error("websocket error call_sid={} error={}", call_sid, str(e))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/")
async def root():
    return {
        "system": "REI Agent",
        "business": os.environ.get("BUSINESS_NAME"),
        "agent": os.environ.get("AGENT_NAME"),
        "status": "operational",
    }
