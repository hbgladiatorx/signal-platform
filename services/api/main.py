"""FastAPI application entry point.

Composes routers, middleware, lifecycle, and exposes `app` for gunicorn/uvicorn.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import orjson
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from packages.data.db import dispose_engine, get_engine
from services.api.redis_subscriber import broadcaster
from services.api.routers import (
    backtests,
    copilot,
    health,
    instruments,
    live,
    market,
    me,
    ml,
    paper_sessions,
    settings as settings_router,
    strategies,
    system,
    user_strategies,
    walkforwards,
    ws,
)


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(
                serializer=lambda d, **k: orjson.dumps(d).decode()
            ),
        ],
    )


_configure_logging()
log = structlog.get_logger(__name__)


REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("api.starting", env=os.environ.get("ENV", "unknown"))
    get_engine()
    await broadcaster.start(REDIS_URL)
    # Seed shared platform broker credentials from env so any user can deploy
    # without first connecting their own key. Idempotent; non-fatal on error.
    try:
        from packages.data.platform_credentials import seed_platform_credentials

        services = await seed_platform_credentials(get_engine())
        log.info("api.platform_credentials_seeded", services=services)
    except Exception as e:  # noqa: BLE001
        log.error("api.platform_credentials_seed_failed", err=str(e))
    log.info("api.ready")
    yield
    log.info("api.shutting_down")
    await broadcaster.stop()
    await dispose_engine()
    log.info("api.stopped")


app = FastAPI(
    title="Signal Platform API",
    description=(
        "Multi-asset quantitative research and trading platform.\n\n"
        "Phase 1: market data ingestion, queryable history, live websocket,\n"
        "operations health dashboard, and user settings.\n"
        "Phase 2+: strategies, backtests, paper trading, live execution."
    ),
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=JSONResponse,
)


_cors_origins_env = os.environ.get("CORS_ORIGINS", "*")
_cors_origins = (
    ["*"]
    if _cors_origins_env == "*"
    else [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    log.info(
        "api.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration_ms, 2),
    )
    return response


app.include_router(health.router)
app.include_router(instruments.router)
app.include_router(market.router)
app.include_router(me.router)
app.include_router(system.router)
app.include_router(settings_router.router)
app.include_router(strategies.router)
app.include_router(backtests.router)
app.include_router(user_strategies.router)
app.include_router(walkforwards.router)
app.include_router(ml.router)
app.include_router(paper_sessions.router)
app.include_router(live.router)
app.include_router(copilot.router)
app.include_router(ws.router)


@app.get("/")
async def root() -> dict:
    return {
        "service": "signal-platform-api",
        "version": "0.1.0",
        "docs": "/docs",
    }
