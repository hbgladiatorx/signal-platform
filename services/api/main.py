"""FastAPI application entry point.

Composes the routers, configures middleware (CORS, structured logging),
and exposes `app` for uvicorn to serve.

Run locally:
    uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload

Run in production (Docker):
    gunicorn services.api.main:app \
        -k uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:8000 \
        --workers 2
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
from services.api.routers import health, instruments, market, me


# ============================================================
# Logging
# ============================================================


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


# ============================================================
# Lifespan: warm up DB connection at startup, dispose on shutdown
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("api.starting", env=os.environ.get("ENV", "unknown"))
    # Initialize the DB engine on startup so the first request doesn't
    # pay the connection-pool warmup cost.
    get_engine()
    log.info("api.ready")
    yield
    log.info("api.shutting_down")
    await dispose_engine()
    log.info("api.stopped")


# ============================================================
# Application
# ============================================================


app = FastAPI(
    title="Signal Platform API",
    description=(
        "Multi-asset quantitative research and trading platform.\n\n"
        "Phase 1: market data ingestion and queryable history.\n"
        "Phase 2+: strategies, backtests, paper trading, live execution."
    ),
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=JSONResponse,
)


# ============================================================
# CORS
# ============================================================


# In production, lock these down to the actual frontend origin.
# For Step 7 we allow any origin so curl from your Mac works.
# Step 9 (Caddy) will restrict this.
_cors_origins_env = os.environ.get("CORS_ORIGINS", "*")
_cors_origins = (
    ["*"] if _cors_origins_env == "*" else [o.strip() for o in _cors_origins_env.split(",")]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================
# Request logging middleware
# ============================================================


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


# ============================================================
# Routers
# ============================================================


app.include_router(health.router)
app.include_router(instruments.router)
app.include_router(market.router)
app.include_router(me.router)


# ============================================================
# Root
# ============================================================


@app.get("/")
async def root() -> dict:
    return {
        "service": "signal-platform-api",
        "version": "0.1.0",
        "docs": "/docs",
    }
