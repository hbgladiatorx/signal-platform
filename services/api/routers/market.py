"""Market data endpoints.

GET /market/trades                 — recent trades for an instrument
GET /market/quotes                 — recent L1 quotes for an instrument (newest first)
GET /market/quotes/recent          — recent L1 quotes ordered oldest first for charting
GET /market/quote/latest           — most recent quote with mid/spread
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide
from services.api.deps import get_db_session

router = APIRouter(prefix="/market", tags=["market"])


class LatestQuoteResponse(BaseModel):
    """Latest L1 quote response with computed mid/spread fields."""

    canonical_symbol: str
    ts: datetime
    bid: Decimal | None = None
    bid_size: Decimal | None = None
    ask: Decimal | None = None
    ask_size: Decimal | None = None
    mid: Decimal | None = None
    spread: Decimal | None = None
    spread_bps: Decimal | None = None


class QuoteChartPoint(BaseModel):
    """Compact quote point for chart consumption (oldest first ordering)."""

    ts: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None


async def _resolve_instrument_id(
    canonical_symbol: str,
    session: AsyncSession,
) -> int:
    """Look up the instrument_id for a canonical symbol or raise 404."""
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


@router.get("/trades", response_model=list[TradeEvent])
async def list_recent_trades(
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
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
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
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


@router.get("/quotes/recent", response_model=list[QuoteChartPoint])
async def list_recent_quotes_for_chart(
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    minutes: int = Query(
        default=60,
        ge=1,
        le=1440,
        description="Look-back window in minutes (default 60)",
    ),
    max_points: int = Query(
        default=2000,
        ge=1,
        le=10_000,
        description="Hard cap on returned points",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[QuoteChartPoint]:
    """
    Return L1 quotes for the chart, ordered OLDEST first so the frontend
    can append live updates to the right side without resorting.

    For Phase 1 we return raw points without resampling. The `max_points`
    cap protects against pulling millions of rows if minutes is large and
    the venue is chatty.
    """
    instrument_id = await _resolve_instrument_id(symbol, session)
    result = await session.execute(
        text(
            """
            SELECT ts, bid, ask
            FROM quotes_l1
            WHERE instrument_id = :instrument_id
              AND ts >= NOW() - (:minutes * INTERVAL '1 minute')
            ORDER BY ts ASC
            LIMIT :max_points
            """
        ),
        {
            "instrument_id": instrument_id,
            "minutes": minutes,
            "max_points": max_points,
        },
    )
    points: list[QuoteChartPoint] = []
    for row in result.mappings():
        bid = row["bid"]
        ask = row["ask"]
        mid: Decimal | None = None
        if bid is not None and ask is not None:
            mid = (bid + ask) / Decimal("2")
        points.append(
            QuoteChartPoint(ts=row["ts"], bid=bid, ask=ask, mid=mid)
        )
    return points


@router.get("/quote/latest", response_model=LatestQuoteResponse)
async def get_latest_quote(
    symbol: str = Query(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS"),
    session: AsyncSession = Depends(get_db_session),
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
