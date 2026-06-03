"""Polygon.io API — equities market data and catalog sync.

A dedicated, venue-specific REST surface over Polygon (distinct from the
venue-agnostic ``/market`` endpoints, which serve data the platform has already
ingested into TimescaleDB). These call Polygon live:

  GET  /polygon/status                 — Polygon connectivity + market status
  GET  /polygon/tickers                — search the Polygon ticker universe
  GET  /polygon/aggregates             — OHLC aggregate bars for a ticker
  GET  /polygon/last-trade             — most recent trade
  GET  /polygon/last-quote             — most recent NBBO quote
  POST /polygon/sync-universe          — upsert Polygon tickers as instruments

All endpoints require auth and a configured POLYGON_API_KEY (else 503).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.adapters.equity.polygon import PolygonClient, to_canonical
from packages.core.exceptions import AdapterError, ConfigError
from services.api.auth import get_current_user
from services.api.deps import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/polygon", tags=["polygon"])

BarResolution = Literal["1m", "5m", "15m", "1h", "4h", "1d"]


def _client() -> PolygonClient:
    try:
        return PolygonClient()
    except ConfigError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Polygon is not configured: {e}",
        )


# ============================================================
# Schemas
# ============================================================
class AggregateBar(BaseModel):
    ts: int = Field(..., description="Bar open time, epoch ms")
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None


class AggregatesResponse(BaseModel):
    symbol: str
    resolution: str
    bars: list[AggregateBar]


class SyncUniverseRequest(BaseModel):
    search: str | None = Field(default=None, description="Filter tickers by name/symbol")
    limit: int = Field(default=100, ge=1, le=1000)
    activate: bool = Field(default=False)


class SyncUniverseResponse(BaseModel):
    venue: str = "POLYGON"
    tickers_fetched: int
    inserted_or_updated: int
    activated: bool


# ============================================================
# Endpoints
# ============================================================
@router.get("/status")
async def polygon_status(_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    client = _client()
    try:
        status = await client.market_status()
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()
    return {"configured": True, "market": status}


@router.get("/tickers")
async def polygon_tickers(
    search: str | None = Query(default=None),
    market: str = Query(default="stocks"),
    limit: int = Query(default=100, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    client = _client()
    try:
        return await client.list_tickers(market=market, search=search, limit=limit)
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()


@router.get("/aggregates", response_model=AggregatesResponse)
async def polygon_aggregates(
    symbol: str = Query(..., description="Ticker (AAPL) or canonical (AAPL-USD@POLYGON)"),
    resolution: BarResolution = Query(default="1d"),
    start: str = Query(..., alias="from", description="YYYY-MM-DD or epoch ms"),
    end: str = Query(..., alias="to", description="YYYY-MM-DD or epoch ms"),
    adjusted: bool = Query(default=True),
    _user: dict = Depends(get_current_user),
) -> AggregatesResponse:
    ticker = symbol.split("-", 1)[0].split("@", 1)[0].upper()
    client = _client()
    try:
        results = await client.aggregates(
            ticker, resolution=resolution, start=start, end=end, adjusted=adjusted
        )
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()
    bars = [
        AggregateBar(
            ts=int(r["t"]),
            open=float(r["o"]),
            high=float(r["h"]),
            low=float(r["l"]),
            close=float(r["c"]),
            volume=float(r.get("v", 0)),
            vwap=float(r["vw"]) if r.get("vw") is not None else None,
            trade_count=int(r["n"]) if r.get("n") is not None else None,
        )
        for r in results
    ]
    return AggregatesResponse(symbol=ticker, resolution=resolution, bars=bars)


@router.get("/last-trade")
async def polygon_last_trade(
    symbol: str = Query(...),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    ticker = symbol.split("-", 1)[0].split("@", 1)[0].upper()
    client = _client()
    try:
        return await client.last_trade(ticker)
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()


@router.get("/last-quote")
async def polygon_last_quote(
    symbol: str = Query(...),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    ticker = symbol.split("-", 1)[0].split("@", 1)[0].upper()
    client = _client()
    try:
        return await client.last_quote(ticker)
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()


@router.post("/sync-universe", response_model=SyncUniverseResponse)
async def polygon_sync_universe(
    body: SyncUniverseRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> SyncUniverseResponse:
    """Import Polygon tickers into the instrument catalog as equities.

    Each Polygon stock ticker becomes an instrument ``{TICKER}-USD@POLYGON``
    so it can be backtested (after a Polygon backfill) and tracked. Idempotent.
    """
    body = body or SyncUniverseRequest()
    client = _client()
    try:
        tickers = await client.list_tickers(
            market="stocks", search=body.search, limit=body.limit
        )
    except AdapterError as e:
        raise HTTPException(502, str(e))
    finally:
        await client.close()

    rows = []
    for t in tickers:
        ticker = t.get("ticker")
        if not ticker:
            continue
        rows.append(
            {
                "canonical_symbol": to_canonical(ticker),
                "native_symbol": ticker.upper(),
                "base": ticker.upper(),
                "quote": "USD",
                "metadata": json.dumps(
                    {
                        "name": t.get("name"),
                        "primary_exchange": t.get("primary_exchange"),
                        "type": t.get("type"),
                    }
                ),
                "active": body.activate,
            }
        )

    if rows:
        await session.execute(
            text(
                """
                INSERT INTO instruments
                    (asset_class, canonical_symbol, venue, native_symbol, base,
                     quote, metadata, active)
                VALUES
                    ('equity', :canonical_symbol, 'POLYGON', :native_symbol,
                     :base, :quote, CAST(:metadata AS JSONB), :active)
                ON CONFLICT (canonical_symbol) DO UPDATE SET
                    native_symbol = EXCLUDED.native_symbol,
                    base = EXCLUDED.base,
                    quote = EXCLUDED.quote,
                    metadata = instruments.metadata || EXCLUDED.metadata
                """
            ),
            rows,
        )
        await session.commit()

    return SyncUniverseResponse(
        tickers_fetched=len(tickers),
        inserted_or_updated=len(rows),
        activated=body.activate,
    )
