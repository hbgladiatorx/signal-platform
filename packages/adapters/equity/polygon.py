"""Polygon.io adapter — equities market data.

Two surfaces, matching how the platform already separates data fetching from
streaming:

  - :class:`PolygonClient`: a thin async REST client over the endpoints the
    new ``/polygon`` API and the historical backfill need (aggregate bars,
    last trade/quote, ticker reference, market status).

  - :class:`PolygonAdapter`: an :class:`AssetAdapter` so Polygon plugs into the
    same ingestion path as Binance.US. It streams trades/quotes from Polygon's
    stocks WebSocket and emits canonical TradeEvent/QuoteL1Event objects.

Canonical symbols use the platform's ``{BASE}-{QUOTE}@{VENUE}`` shape with a
synthetic USD quote for equities: ``AAPL`` ⇄ ``AAPL-USD@POLYGON``.

API key resolution: explicit constructor arg, else ``POLYGON_API_KEY`` env.
Docs: https://polygon.io/docs/stocks
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiohttp
import structlog
import websockets

from packages.adapters.base import AssetAdapter
from packages.core.exceptions import AdapterError, ConfigError
from packages.core.models import QuoteL1Event, TradeEvent

log = structlog.get_logger(__name__)

VENUE = "POLYGON"
QUOTE_CCY = "USD"
REST_BASE = "https://api.polygon.io"
WS_STOCKS_URL = "wss://socket.polygon.io/stocks"

# Polygon timespan mapping for our canonical bar resolutions.
RESOLUTION_TO_POLYGON: dict[str, tuple[int, str]] = {
    "1m": (1, "minute"),
    "5m": (5, "minute"),
    "15m": (15, "minute"),
    "1h": (1, "hour"),
    "4h": (4, "hour"),
    "1d": (1, "day"),
}


def to_native(canonical_symbol: str) -> str:
    """'AAPL-USD@POLYGON' -> 'AAPL'."""
    if "@" not in canonical_symbol:
        raise AdapterError(f"canonical symbol missing venue suffix: {canonical_symbol}")
    symbol_part, venue = canonical_symbol.split("@", 1)
    if venue != VENUE:
        raise AdapterError(f"venue mismatch: {venue} (expected {VENUE})")
    # Strip the synthetic quote if present.
    return symbol_part.split("-", 1)[0].upper()


def to_canonical(native_symbol: str) -> str:
    """'AAPL' -> 'AAPL-USD@POLYGON'."""
    return f"{native_symbol.upper()}-{QUOTE_CCY}@{VENUE}"


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("POLYGON_API_KEY")
    if not key:
        raise ConfigError("POLYGON_API_KEY is not set in the environment")
    return key


class PolygonClient:
    """Async REST client for Polygon.io stock endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = REST_BASE,
    ) -> None:
        self._api_key = _resolve_api_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}{path}"
        async with session.get(
            url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            payload = await resp.json(content_type=None)
            if resp.status == 401:
                raise AdapterError("Polygon rejected the API key (HTTP 401)")
            if resp.status == 429:
                raise AdapterError("Polygon rate limit hit (HTTP 429)")
            if resp.status >= 400:
                msg = payload.get("error") or payload.get("message") if isinstance(
                    payload, dict
                ) else str(payload)
                raise AdapterError(f"Polygon {path} failed (HTTP {resp.status}): {msg}")
            return payload

    async def market_status(self) -> dict:
        return await self._get("/v1/marketstatus/now")

    async def list_tickers(
        self,
        *,
        market: str = "stocks",
        search: str | None = None,
        active: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "market": market,
            "active": str(active).lower(),
            "limit": min(limit, 1000),
        }
        if search:
            params["search"] = search
        payload = await self._get("/v3/reference/tickers", params)
        return payload.get("results", [])

    async def aggregates(
        self,
        ticker: str,
        *,
        resolution: str,
        start: str,
        end: str,
        adjusted: bool = True,
        limit: int = 50000,
    ) -> list[dict]:
        """Aggregate bars. `start`/`end` are YYYY-MM-DD or epoch-ms strings."""
        if resolution not in RESOLUTION_TO_POLYGON:
            raise AdapterError(f"unsupported resolution: {resolution}")
        mult, span = RESOLUTION_TO_POLYGON[resolution]
        path = f"/v2/aggs/ticker/{ticker.upper()}/range/{mult}/{span}/{start}/{end}"
        payload = await self._get(
            path,
            {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": limit},
        )
        return payload.get("results", [])

    async def last_trade(self, ticker: str) -> dict:
        payload = await self._get(f"/v2/last/trade/{ticker.upper()}")
        return payload.get("results", payload)

    async def last_quote(self, ticker: str) -> dict:
        payload = await self._get(f"/v2/last/nbbo/{ticker.upper()}")
        return payload.get("results", payload)

    async def close(self) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None


class PolygonAdapter(AssetAdapter):
    """AssetAdapter for Polygon's stocks WebSocket (trades + NBBO quotes)."""

    venue = VENUE

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = _resolve_api_key(api_key)

    def to_native_symbol(self, canonical_symbol: str) -> str:
        return to_native(canonical_symbol)

    def to_canonical_symbol(self, native_symbol: str) -> str:
        return to_canonical(native_symbol)

    async def stream_trades(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[TradeEvent]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        channels = [f"T.{s}" for s in native]
        async for event in self._stream(channels, self._parse_trade):
            yield event

    async def stream_quotes_l1(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[QuoteL1Event]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        channels = [f"Q.{s}" for s in native]
        async for event in self._stream(channels, self._parse_quote):
            yield event

    async def _stream(
        self,
        channels: list[str],
        parser: Callable[[dict[str, Any]], Any],
    ) -> AsyncIterator[Any]:
        backoff = 1
        while True:
            try:
                log.info("polygon.connecting", channels=channels, backoff=backoff)
                async with websockets.connect(
                    WS_STOCKS_URL, ping_interval=20, ping_timeout=20
                ) as ws:
                    await ws.send(json.dumps({"action": "auth", "params": self._api_key}))
                    await ws.send(
                        json.dumps({"action": "subscribe", "params": ",".join(channels)})
                    )
                    log.info("polygon.connected", channels=channels)
                    backoff = 1
                    async for raw in ws:
                        try:
                            messages = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(messages, list):
                            messages = [messages]
                        for msg in messages:
                            event = parser(msg)
                            if event is not None:
                                yield event
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("polygon.disconnected", error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _parse_trade(self, msg: dict[str, Any]) -> TradeEvent | None:
        # Trade event: {"ev":"T","sym":"AAPL","p":price,"s":size,"t":epoch_ms,...}
        if msg.get("ev") != "T" or "sym" not in msg:
            return None
        ts = datetime.fromtimestamp(msg["t"] / 1000, tz=UTC)
        return TradeEvent(
            canonical_symbol=self.to_canonical_symbol(msg["sym"]),
            ts=ts,
            price=Decimal(str(msg["p"])),
            quantity=Decimal(str(msg.get("s", 0))),
            side=None,  # Polygon trades don't carry an aggressor side
            venue_trade_id=str(msg.get("i", msg.get("t"))),
        )

    def _parse_quote(self, msg: dict[str, Any]) -> QuoteL1Event | None:
        # Quote event: {"ev":"Q","sym":"AAPL","bp":bid,"bs":bidsz,"ap":ask,"as":asksz,"t":ms}
        if msg.get("ev") != "Q" or "sym" not in msg:
            return None
        ts = datetime.fromtimestamp(msg["t"] / 1000, tz=UTC) if msg.get(
            "t"
        ) else datetime.now(tz=UTC)
        return QuoteL1Event(
            canonical_symbol=self.to_canonical_symbol(msg["sym"]),
            ts=ts,
            bid=Decimal(str(msg["bp"])) if msg.get("bp") is not None else None,
            bid_size=Decimal(str(msg["bs"])) if msg.get("bs") is not None else None,
            ask=Decimal(str(msg["ap"])) if msg.get("ap") is not None else None,
            ask_size=Decimal(str(msg["as"])) if msg.get("as") is not None else None,
        )
