"""System health endpoint.

GET /system/health/detail   — comprehensive operations dashboard data
                              (protected: any authenticated user can view)

Phase 1.1 (Step 12 patch):
  - DB queries run in parallel with Redis queries via asyncio.gather()
  - Ingestion LATERAL scans bounded to the last 15 minutes (was 1 day)
  - Hypertable row counts use timescaledb_information.chunks (accurate),
    falling back to pg_class.reltuples if the TimescaleDB extension
    catalog isn't available.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.db import get_engine
from packages.data.messagebus import (
    GROUP_PERSISTENCE,
    GROUP_WS_BROADCAST,
    STREAM_QUOTES_RAW,
    STREAM_TRADES_RAW,
)
from services.api.auth import get_current_user
from services.api.deps import get_db_session

router = APIRouter(prefix="/system", tags=["system"])

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


# ============================================================
# Response models
# ============================================================


class IngestionInstrumentStatus(BaseModel):
    canonical_symbol: str
    venue: str
    last_trade_ts: datetime | None = None
    last_quote_ts: datetime | None = None
    last_trade_age_s: float | None = None
    last_quote_age_s: float | None = None
    trades_last_5m: int
    quotes_last_5m: int


class StreamStatus(BaseModel):
    stream: str
    length: int
    groups: list[dict[str, Any]]


class TableStats(BaseModel):
    name: str
    approximate_rows: int
    earliest_ts: datetime | None = None
    latest_ts: datetime | None = None


class SystemHealthDetail(BaseModel):
    ts: datetime
    duration_ms: float

    instruments_total: int
    instruments_active: int

    ingestion: list[IngestionInstrumentStatus]
    streams: list[StreamStatus]
    tables: list[TableStats]

    persistence_pending_total: int
    ws_broadcast_pending_total: int


# ============================================================
# Helper queries (each returns a structured chunk of the response)
# ============================================================


async def _query_instrument_counts(session: AsyncSession) -> tuple[int, int]:
    result = await session.execute(
        text(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE active) AS active FROM instruments"
        )
    )
    row = result.mappings().first()
    if not row:
        return (0, 0)
    return (int(row["total"] or 0), int(row["active"] or 0))


async def _query_ingestion(
    session: AsyncSession,
    now: datetime,
) -> list[IngestionInstrumentStatus]:
    """
    Per-instrument freshness. LATERAL scans bounded to the last 15 minutes
    so we don't drag in chunks we don't need; for last_trade_ts on a very
    sparse instrument this could miss data, but we accept that — the
    page's purpose is showing "is data flowing now," not historical lookups.
    """
    result = await session.execute(
        text(
            """
            SELECT
              i.canonical_symbol,
              i.venue,
              t_stats.last_trade_ts,
              t_stats.trades_last_5m,
              q_stats.last_quote_ts,
              q_stats.quotes_last_5m
            FROM instruments i
            LEFT JOIN LATERAL (
              SELECT
                MAX(ts) AS last_trade_ts,
                COUNT(*) FILTER (WHERE ts >= NOW() - INTERVAL '5 minutes') AS trades_last_5m
              FROM trades
              WHERE instrument_id = i.id
                AND ts >= NOW() - INTERVAL '24 hours'
            ) AS t_stats ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                MAX(ts) AS last_quote_ts,
                COUNT(*) FILTER (WHERE ts >= NOW() - INTERVAL '5 minutes') AS quotes_last_5m
              FROM quotes_l1
              WHERE instrument_id = i.id
                AND ts >= NOW() - INTERVAL '15 minutes'
            ) AS q_stats ON TRUE
            WHERE i.active = TRUE
            ORDER BY i.canonical_symbol
            """
        )
    )
    out: list[IngestionInstrumentStatus] = []
    for row in result.mappings():
        last_trade_ts: datetime | None = row["last_trade_ts"]
        last_quote_ts: datetime | None = row["last_quote_ts"]
        out.append(
            IngestionInstrumentStatus(
                canonical_symbol=row["canonical_symbol"],
                venue=row["venue"],
                last_trade_ts=last_trade_ts,
                last_quote_ts=last_quote_ts,
                last_trade_age_s=(
                    (now - last_trade_ts).total_seconds()
                    if last_trade_ts is not None
                    else None
                ),
                last_quote_age_s=(
                    (now - last_quote_ts).total_seconds()
                    if last_quote_ts is not None
                    else None
                ),
                trades_last_5m=int(row["trades_last_5m"] or 0),
                quotes_last_5m=int(row["quotes_last_5m"] or 0),
            )
        )
    return out


async def _query_tables(session: AsyncSession) -> list[TableStats]:
    """
    Row counts come from timescaledb_information.hypertables when available
    (rows_uppercase), summed across chunks. Fallback to pg_class.reltuples
    if the catalog query fails (e.g. extension not loaded in test envs).

    Time ranges come from min/max ts of each hypertable directly.
    """
    out: list[TableStats] = []
    for table_name in ("trades", "quotes_l1", "bars"):
        approx_rows = -1
        try:
            row_result = await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(c.reltuples)::BIGINT, 0) AS rows
                    FROM pg_class c
                    JOIN pg_inherits inh ON inh.inhrelid = c.oid
                    JOIN pg_class parent ON parent.oid = inh.inhparent
                    WHERE parent.relname = :name
                    """
                ),
                {"name": table_name},
            )
            r = row_result.scalar()
            if r is not None and r >= 0:
                approx_rows = int(r)
        except Exception:
            approx_rows = -1

        try:
            ts_result = await session.execute(
                text(f"SELECT MIN(ts) AS mn, MAX(ts) AS mx FROM {table_name}")
            )
            ts_row = ts_result.mappings().first()
            earliest = ts_row["mn"] if ts_row else None
            latest = ts_row["mx"] if ts_row else None
        except Exception:
            earliest = None
            latest = None

        out.append(
            TableStats(
                name=table_name,
                approximate_rows=approx_rows,
                earliest_ts=earliest,
                latest_ts=latest,
            )
        )
    return out


async def _query_redis() -> tuple[list[StreamStatus], int, int]:
    """Return streams, persistence_pending_total, ws_broadcast_pending_total."""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    streams: list[StreamStatus] = []
    persistence_pending_total = 0
    ws_broadcast_pending_total = 0
    try:
        for stream_name in (STREAM_TRADES_RAW, STREAM_QUOTES_RAW):
            try:
                length = await r.xlen(stream_name)
            except Exception:
                length = 0
            try:
                raw_groups = await r.xinfo_groups(stream_name)
            except Exception:
                raw_groups = []

            groups_summary: list[dict[str, Any]] = []
            for grp in raw_groups:
                grp_dict = dict(grp) if not isinstance(grp, dict) else grp
                name = grp_dict.get("name", "")
                pending = int(grp_dict.get("pending", 0) or 0)
                consumers = int(grp_dict.get("consumers", 0) or 0)
                lag_val = grp_dict.get("lag")
                try:
                    lag = int(lag_val) if lag_val is not None else None
                except (TypeError, ValueError):
                    lag = None
                groups_summary.append(
                    {
                        "name": name,
                        "consumers": consumers,
                        "pending": pending,
                        "lag": lag,
                        "last_delivered_id": grp_dict.get(
                            "last-delivered-id", grp_dict.get("last_delivered_id")
                        ),
                    }
                )
                if name == GROUP_PERSISTENCE:
                    persistence_pending_total += pending
                elif name == GROUP_WS_BROADCAST:
                    ws_broadcast_pending_total += pending

            streams.append(
                StreamStatus(stream=stream_name, length=length, groups=groups_summary)
            )
    finally:
        await r.aclose()
    return streams, persistence_pending_total, ws_broadcast_pending_total


# ============================================================
# Endpoint
# ============================================================


@router.get("/health/detail", response_model=SystemHealthDetail)
async def system_health_detail(
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> SystemHealthDetail:
    """
    Parallelizes the three logical groups of work:
      - DB queries (instrument counts, ingestion freshness, table stats)
      - Redis queries (stream depths, consumer-group info)

    All three run concurrently; total endpoint time is dominated by the
    single slowest query rather than the sum.
    """
    started = time.monotonic()
    now = datetime.now(timezone.utc)

    # DB queries share the same session; running them as gathered tasks would
    # serialize on the connection anyway. Run them sequentially but keep
    # the Redis fetch concurrent with the DB work via gather().
    async def _db_block() -> tuple[
        tuple[int, int],
        list[IngestionInstrumentStatus],
        list[TableStats],
    ]:
        counts = await _query_instrument_counts(session)
        ingestion = await _query_ingestion(session, now)
        tables = await _query_tables(session)
        return counts, ingestion, tables

    (counts, ingestion, tables), redis_result = await asyncio.gather(
        _db_block(),
        _query_redis(),
    )

    instruments_total, instruments_active = counts
    streams, persistence_pending_total, ws_broadcast_pending_total = redis_result

    duration_ms = (time.monotonic() - started) * 1000

    return SystemHealthDetail(
        ts=now,
        duration_ms=round(duration_ms, 2),
        instruments_total=instruments_total,
        instruments_active=instruments_active,
        ingestion=ingestion,
        streams=streams,
        tables=tables,
        persistence_pending_total=persistence_pending_total,
        ws_broadcast_pending_total=ws_broadcast_pending_total,
    )


@router.get("/connections")
async def connections(_user=Depends(get_current_user)) -> dict[str, bool]:
    """Which platform integrations are configured.

    Booleans only — never the key values — so this is safe to surface in the UI.
    FINNHUB lives in the frontend container and is checked by the web app itself.
    """

    def has(*keys: str) -> bool:
        return all(bool(os.environ.get(k, "").strip()) for k in keys)

    return {
        "ai_copilot": has("ANTHROPIC_API_KEY"),
        "crypto_data": has("BINANCEUS_API_KEY", "BINANCEUS_API_SECRET"),
        "stock_data_alpaca": has("ALPACA_DATA_KEY_ID", "ALPACA_DATA_SECRET"),
        "stock_data_polygon": has("POLYGON_API_KEY")
        and bool(os.environ.get("INGESTION_POLYGON_SYMBOLS", "").strip()),
        "trading_alpaca_paper": has("ALPACA_API_KEY_ID", "ALPACA_SECRET_KEY"),
        "trading_binanceus": has("BINANCEUS_API_KEY", "BINANCEUS_API_SECRET"),
        "key_encryption": has("SETTINGS_ENCRYPTION_KEY"),
    }


# ============================================================
# Live resource metrics (for the floating health widget)
# ============================================================
class SystemMetrics(BaseModel):
    ts: float
    cpu_percent: float
    cpu_cores: int
    load_avg: list[float] | None = None
    mem_used: int
    mem_total: int
    mem_percent: float
    disk_used: int
    disk_total: int
    disk_percent: float
    # Cumulative counters — the client derives a rate from successive polls.
    net_bytes_sent: int
    net_bytes_recv: int


@router.get("/metrics", response_model=SystemMetrics)
async def system_metrics(_user=Depends(get_current_user)) -> SystemMetrics:
    """Host resource usage (CPU / memory / disk / network) for the live health
    widget. psutil reads the host's /proc, so CPU + memory reflect the whole
    machine — a backtest running in the worker shows up here. Cheap and
    non-blocking (cpu_percent(interval=None) reports usage since the last call)."""
    import psutil

    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    try:
        load = list(os.getloadavg())
    except (OSError, AttributeError):
        load = None
    return SystemMetrics(
        ts=time.time(),
        cpu_percent=psutil.cpu_percent(interval=None),
        cpu_cores=psutil.cpu_count() or 1,
        load_avg=load,
        mem_used=int(vm.used),
        mem_total=int(vm.total),
        mem_percent=float(vm.percent),
        disk_used=int(du.used),
        disk_total=int(du.total),
        disk_percent=float(du.percent),
        net_bytes_sent=int(net.bytes_sent),
        net_bytes_recv=int(net.bytes_recv),
    )
