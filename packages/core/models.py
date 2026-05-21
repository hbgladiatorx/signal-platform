"""Canonical Pydantic models flowing through the platform.

Every service produces or consumes these. They are the lingua franca
between ingestion, persistence, the API, and downstream consumers.

Decimals are used for all monetary/quantity values instead of floats
because float arithmetic on prices accumulates error.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from packages.core.types import (
    AssetClass,
    BarResolution,
    IngestionStatus,
    TradeSide,
)


class Instrument(BaseModel):
    """A tradable instrument as the platform knows it.

    Mirrors the `instruments` table. The `canonical_symbol` is the
    system-wide identifier; everything else flows from it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: AssetClass
    canonical_symbol: str
    venue: str
    native_symbol: str
    base: str | None = None
    quote: str | None = None
    metadata: dict = Field(default_factory=dict)
    active: bool = True


class TradeEvent(BaseModel):
    """A single executed trade tick. Source-agnostic.

    Adapters translate exchange-native trade messages into this form.
    The persistence worker writes these into the `trades` hypertable.
    """

    canonical_symbol: str
    ts: datetime
    price: Decimal
    quantity: Decimal
    side: TradeSide | None = None
    venue_trade_id: str


class QuoteL1Event(BaseModel):
    """Top-of-book quote update.

    Many exchanges emit best-bid/best-ask updates separately from
    trades. This model captures both sides of the top of the book.
    """

    canonical_symbol: str
    ts: datetime
    bid: Decimal | None = None
    bid_size: Decimal | None = None
    ask: Decimal | None = None
    ask_size: Decimal | None = None


class Bar(BaseModel):
    """OHLCV bar at a defined resolution.

    Either pulled from an exchange's klines API or computed from
    trade ticks downstream.
    """

    canonical_symbol: str
    resolution: BarResolution
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int | None = None
    vwap: Decimal | None = None


class IngestionHealthReport(BaseModel):
    """Periodic health report from an ingestion worker.

    Persisted into the `ingestion_health` hypertable. The API exposes
    the latest report per (source, instrument) pair.
    """

    source: str
    canonical_symbol: str
    status: IngestionStatus
    last_message_ts: datetime | None = None
    message_count_1m: int = 0
    error_message: str | None = None
