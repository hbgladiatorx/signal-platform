"""System health endpoint.

GET /system/health/detail   — comprehensive operations dashboard data
                              (protected: any authenticated user can view)

Returns a single JSON blob with sections for:
  - ingestion freshness per instrument
  - persistence worker queue depth and processing rates
  - Redis stream depths and consumer-group health
  - database row counts and time ranges per hypertable

Designed to be cheap: every query is an indexed aggregate or a Redis
command, total response time should be <100ms.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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

    # Persistence worker queue depth: total pending messages waiting
    # to be acknowledged by the `persistence` consumer group.
    persistence_pending_total: int
    ws_broadcast_pending_total: int


# ============================================================
# Endpoint
# ============================================================


@router.get("/health/detail", response_model=SystemHealthDetail)
async def system_health_detail(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> SystemHealthDetail:
    started = time.monotonic()
    now = datetime.now(timezone.utc)

    # ----- Instrument counts -----
    inst_count_result = await session.execute(
        text(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE active) AS active FROM instruments"
        )
    )
    inst_counts = inst_count_result.mappings().first()
    instruments_total = inst_counts["total"] if inst_counts else 0
    instruments_active = inst_counts["active"] if inst_counts else 0

    # ----- Per-instrument ingestion freshness -----
    ingestion_result = await session.execute(
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
                AND ts >= NOW() - INTERVAL '1 day'
            ) AS t_stats ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                MAX(ts) AS last_quote_ts,
                COUNT(*) FILTER (WHERE ts >= NOW() - INTERVAL '5 minutes') AS quotes_last_5m
              FROM quotes_l1
              WHERE instrument_id = i.id
                AND ts >= NOW() - INTERVAL '1 day'
            ) AS q_stats ON TRUE
            WHERE i.active = TRUE
            ORDER BY i.canonical_symbol
            """
        )
    )
    ingestion: list[IngestionInstrumentStatus] = []
    for row in ingestion_result.mappings():
        last_trade_ts: datetime | None = row["last_trade_ts"]
        last_quote_ts: datetime | None = row["last_quote_ts"]
        ingestion.append(
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
                trades_last_5m=row["trades_last_5m"] or 0,
                quotes_last_5m=row["quotes_last_5m"] or 0,
            )
        )

    # ----- Hypertable stats -----
    table_stats_result = await session.execute(
        text(
            """
            SELECT 'trades' AS name,
                   COALESCE((SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'trades'), 0) AS approximate_rows,
                   (SELECT MIN(ts) FROM trades) AS earliest_ts,
                   (SELECT MAX(ts) FROM trades) AS latest_ts
            UNION ALL
            SELECT 'quotes_l1' AS name,
                   COALESCE((SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'quotes_l1'), 0) AS approximate_rows,
                   (SELECT MIN(ts) FROM quotes_l1) AS earliest_ts,
                   (SELECT MAX(ts) FROM quotes_l1) AS latest_ts
            UNION ALL
            SELECT 'bars' AS name,
                   COALESCE((SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'bars'), 0) AS approximate_rows,
                   (SELECT MIN(ts) FROM bars) AS earliest_ts,
                   (SELECT MAX(ts) FROM bars) AS latest_ts
            ORDER BY name
            """
        )
    )
    tables: list[TableStats] = []
    for row in table_stats_result.mappings():
        tables.append(
            TableStats(
                name=row["name"],
                approximate_rows=int(row["approximate_rows"] or 0),
                earliest_ts=row["earliest_ts"],
                latest_ts=row["latest_ts"],
            )
        )

    # ----- Redis stream info -----
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
                # xinfo_groups returns lists or dicts depending on redis-py version.
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
                StreamStatus(
                    stream=stream_name, length=length, groups=groups_summary
                )
            )
    finally:
        await r.aclose()

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
