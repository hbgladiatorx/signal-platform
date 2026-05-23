"""Market data endpoints.

GET /market/trades                — recent trades for an instrument
GET /market/quotes                — recent L1 quotes for an instrument
GET /market/quote/latest          — most recent quote with computed mid/spread
GET /market/bars                  — OHLCV bars at one of six resolutions

Bars are sourced from the continuous aggregates created in Steps 15-16:
    1m  → cagg_bars_1m
    5m  → cagg_bars_5m
    15m → cagg_bars_15m
    1h  → cagg_bars_1h
    4h  → cagg_bars_4h
    1d  → cagg_bars_1d
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide
from services.api.auth import get_current_user
from services.api.deps import get_db_session

router = APIRouter(prefix="/market", tags=["market"])


# ============================================================
# Resolution → table-name mapping (whitelist; no string interpolation
# of user input into SQL)
# ============================================================
BarResolution = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

RESOLUTION_TABLE: dict[str, str] = {
    "1m": "cagg_bars_1m",
    "5m": "cagg_bars_5m",
    "15m": "cagg_bars_15m",
    "1h": "cagg_bars_1h",
    "4h": "cagg_bars_4h",
    "1d": "cagg_bars_1d",
}

RESOLUTION_DEFAULT_LOOKBACK: dict[str, timedelta] = {
    "1m": timedelta(hours=2),
    "5m": timedelta(hours=8),
    "15m": timedelta(days=1),
    "1h": timedelta(days=5),
    "4h": timedelta(days=20),
    "1d": timedelta(days=365),
}


# ============================================================
# Response models
# ============================================================


class LatestQuoteResponse(BaseModel):
    canonical_symbol: str
    ts: datetime
    bid: Decimal | None = None
    bid_size: Decimal | None = None
    ask: Decimal | None = None
    ask_size: Decimal | None = None
    mid: Decimal | None = None
    spread: Decimal | None = None
    spread_bps: Decimal | None = None


class Bar(BaseModel):
    """OHLCV bar from a continuous aggregate."""

    bucket: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    vwap: Decimal | None = None


class BarsResponse(BaseModel):
    canonical_symbol: str
    resolution: str
    bars: list[Bar]


# ============================================================
# Helpers
# ============================================================


async def _resolve_instrument_id(
    canonical_symbol: str,
    session: AsyncSession,
) -> int:
    result = await session.execute(
        text("SELECT id FROM instruments WHERE canonical_symbol = :symbol"),
        {"symbol": canonical_symbol},
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {canonical_symbol}",
        )
    return row.id


# ============================================================
# Existing endpoints (preserved from Step 7)
# ============================================================


@router.get("/trades", response_model=list[TradeEvent])
async def list_recent_trades(
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> list[TradeEvent]:
    instrument_id = await _resolve_instrument_id(symbol, session)
    result = await session.execute(
        text(
            """
            SELECT ts, price, quantity, side, venue_trade_id
            FROM trades
            WHERE instrument_id = :instrument_id
            ORDER BY ts DESC
            LIMIT :limit
            """
        ),
        {"instrument_id": instrument_id, "limit": limit},
    )
    trades: list[TradeEvent] = []
    for row in result.mappings():
        side: TradeSide | None = None
        if row["side"]:
            try:
                side = TradeSide(row["side"])
            except ValueError:
                side = None
        trades.append(
            TradeEvent(
                canonical_symbol=symbol,
                ts=row["ts"],
                price=row["price"],
                quantity=row["quantity"],
                side=side,
                venue_trade_id=row["venue_trade_id"],
            )
        )
    return trades


@router.get("/quotes", response_model=list[QuoteL1Event])
async def list_recent_quotes(
    symbol: str = Query(...),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> list[QuoteL1Event]:
    instrument_id = await _resolve_instrument_id(symbol, session)
    result = await session.execute(
        text(
            """
            SELECT ts, bid, bid_size, ask, ask_size
            FROM quotes_l1
            WHERE instrument_id = :instrument_id
            ORDER BY ts DESC
            LIMIT :limit
            """
        ),
        {"instrument_id": instrument_id, "limit": limit},
    )
    quotes: list[QuoteL1Event] = []
    for row in result.mappings():
        quotes.append(
            QuoteL1Event(
                canonical_symbol=symbol,
                ts=row["ts"],
                bid=row["bid"],
                bid_size=row["bid_size"],
                ask=row["ask"],
                ask_size=row["ask_size"],
            )
        )
    return quotes


@router.get("/quote/latest", response_model=LatestQuoteResponse)
async def get_latest_quote(
    symbol: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> LatestQuoteResponse:
    instrument_id = await _resolve_instrument_id(symbol, session)
    result = await session.execute(
        text(
            """
            SELECT ts, bid, bid_size, ask, ask_size
            FROM quotes_l1
            WHERE instrument_id = :instrument_id
            ORDER BY ts DESC
            LIMIT 1
            """
        ),
        {"instrument_id": instrument_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No quotes available for {symbol}",
        )

    bid = row["bid"]
    ask = row["ask"]
    mid: Decimal | None = None
    spread: Decimal | None = None
    spread_bps: Decimal | None = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / Decimal("2")
        spread = ask - bid
        if mid > 0:
            spread_bps = (spread / mid) * Decimal("10000")

    return LatestQuoteResponse(
        canonical_symbol=symbol,
        ts=row["ts"],
        bid=bid,
        bid_size=row["bid_size"],
        ask=ask,
        ask_size=row["ask_size"],
        mid=mid,
        spread=spread,
        spread_bps=spread_bps,
    )


# ============================================================
# NEW: bars endpoint
# ============================================================


@router.get("/bars", response_model=BarsResponse)
async def get_bars(
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    resolution: str = Query(
        default="1m",
        description="Bar resolution. One of: 1m, 5m, 15m, 1h, 4h, 1d",
    ),
    start: datetime | None = Query(
        default=None,
        alias="from",
        description="Inclusive start timestamp (ISO 8601, UTC).",
    ),
    end: datetime | None = Query(
        default=None,
        alias="to",
        description="Exclusive end timestamp (ISO 8601, UTC). Defaults to now.",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Maximum bars to return when no explicit time range given.",
    ),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> BarsResponse:
    """
    Return OHLCV bars for an instrument at the requested resolution.

    Time range resolution:
      - If both `from` and `to` are provided, use them.
      - If `to` is omitted, defaults to NOW().
      - If `from` is omitted, defaults to a resolution-appropriate lookback
        (e.g. 2 hours for 1m, 365 days for 1d).
    """
    table = RESOLUTION_TABLE.get(resolution)
    if not table:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid resolution '{resolution}'. "
                f"Allowed: {sorted(RESOLUTION_TABLE.keys())}"
            ),
        )

    instrument_id = await _resolve_instrument_id(symbol, session)

    end_ts = end or datetime.now(timezone.utc)
    if start is None:
        start_ts = end_ts - RESOLUTION_DEFAULT_LOOKBACK[resolution]
    else:
        start_ts = start

    if start_ts >= end_ts:
        raise HTTPException(
            status_code=400,
            detail="`from` must be strictly less than `to`",
        )

    # Table name is from a whitelist; safe to format into the query.
    query = text(
        f"""
        SELECT
            bucket,
            open,
            high,
            low,
            close,
            volume,
            trade_count,
            CASE WHEN volume_for_vwap > 0
                 THEN price_volume_sum / volume_for_vwap
                 ELSE NULL END AS vwap
        FROM {table}
        WHERE instrument_id = :instrument_id
          AND bucket >= :start_ts
          AND bucket <  :end_ts
        ORDER BY bucket
        LIMIT :limit
        """
    )

    result = await session.execute(
        query,
        {
            "instrument_id": instrument_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "limit": limit,
        },
    )

    bars: list[Bar] = []
    for row in result.mappings():
        bars.append(
            Bar(
                bucket=row["bucket"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                trade_count=row["trade_count"],
                vwap=row["vwap"],
            )
        )

    return BarsResponse(
        canonical_symbol=symbol,
        resolution=resolution,
        bars=bars,
    )
