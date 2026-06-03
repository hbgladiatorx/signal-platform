"""Asset class types and enums used across the platform."""
from __future__ import annotations

from enum import StrEnum


class AssetClass(StrEnum):
    """Categories of tradable instruments."""

    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    OPTION = "option"
    EQUITY = "equity"


class Venue(StrEnum):
    """Trading venues we connect to."""

    BINANCEUS = "BINANCEUS"
    COINBASE = "COINBASE"
    ALPACA = "ALPACA"
    POLYGON = "POLYGON"


class IngestionStatus(StrEnum):
    """Health status reported by ingestion workers."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class BarResolution(StrEnum):
    """OHLCV bar resolutions supported by the platform."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class TradeSide(StrEnum):
    """Trade aggressor side."""

    BUY = "b"
    SELL = "s"
