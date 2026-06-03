"""Price sources for paper-trading fills.

A paper order fills at "the latest price". Where that price comes from is
pluggable:

  - :class:`DBPriceSource` reads the most recent trade (or quote mid) for a
    symbol from the platform's own TimescaleDB tables. Preferred, because it
    reflects exactly the data the platform has ingested.

  - :class:`BinanceTickerPriceSource` hits Binance.US's public ticker endpoint.
    Useful for symbols the platform isn't actively ingesting yet (the bulk of
    the "full universe").

  - :class:`ChainedPriceSource` tries sources in order and returns the first hit.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.execution.base import BrokerError

BINANCE_TICKER_URL = "https://api.binance.us/api/v3/ticker/price"


class PriceSource(Protocol):
    async def get_price(self, canonical_symbol: str, native_symbol: str) -> Decimal | None:
        ...


class DBPriceSource:
    """Latest mark from ingested trades, falling back to the quote mid."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_price(
        self, canonical_symbol: str, native_symbol: str
    ) -> Decimal | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT t.price
                        FROM trades t
                        JOIN instruments i ON i.id = t.instrument_id
                        WHERE i.canonical_symbol = :symbol
                        ORDER BY t.ts DESC
                        LIMIT 1
                        """
                    ),
                    {"symbol": canonical_symbol},
                )
            ).first()
            if row is not None and row[0] is not None:
                return Decimal(str(row[0]))

            # Fall back to the latest top-of-book mid.
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT q.bid, q.ask
                        FROM quotes_l1 q
                        JOIN instruments i ON i.id = q.instrument_id
                        WHERE i.canonical_symbol = :symbol
                        ORDER BY q.ts DESC
                        LIMIT 1
                        """
                    ),
                    {"symbol": canonical_symbol},
                )
            ).first()
            if row is not None and row[0] is not None and row[1] is not None:
                return (Decimal(str(row[0])) + Decimal(str(row[1]))) / Decimal("2")
        return None


class BinanceTickerPriceSource:
    """Public Binance.US ticker price (no auth required)."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_price(
        self, canonical_symbol: str, native_symbol: str
    ) -> Decimal | None:
        session = await self._get_session()
        try:
            async with session.get(
                BINANCE_TICKER_URL,
                params={"symbol": native_symbol},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price = data.get("price")
                return Decimal(str(price)) if price is not None else None
        except (aiohttp.ClientError, TimeoutError):
            return None

    async def close(self) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None


class ChainedPriceSource:
    """Try each source in order; return the first non-None price."""

    def __init__(self, *sources: PriceSource) -> None:
        if not sources:
            raise ValueError("ChainedPriceSource requires at least one source")
        self._sources = sources

    async def get_price(
        self, canonical_symbol: str, native_symbol: str
    ) -> Decimal | None:
        for source in self._sources:
            price = await source.get_price(canonical_symbol, native_symbol)
            if price is not None:
                return price
        return None

    async def require_price(
        self, canonical_symbol: str, native_symbol: str
    ) -> Decimal:
        price = await self.get_price(canonical_symbol, native_symbol)
        if price is None:
            raise BrokerError(
                f"No price available for {canonical_symbol}; cannot fill paper order"
            )
        return price
