import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

load_dotenv()

from backend.api.routes import (
    health,
    properties,
    leads,
    calls,
    sms,
    evals,
    analytics,
)
from backend.voice.webhook import router as voice_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("REI Agent API starting up")
    logger.info("business={}", os.environ.get("BUSINESS_NAME", "unknown"))
    logger.info("agent={}", os.environ.get("AGENT_FULL_NAME", "unknown"))
    yield
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
    allow_credentials=True,
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
app.include_router(voice_router, prefix="/api", tags=["voice"])


@app.get("/")
async def root():
    return {
        "system": "REI Agent",
        "business": os.environ.get("BUSINESS_NAME"),
        "agent": os.environ.get("AGENT_FULL_NAME"),
        "status": "operational",
    }
