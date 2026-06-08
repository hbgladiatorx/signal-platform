"""Binance.US WebSocket adapter.

Documentation: https://docs.binance.us/

Connects to the combined-stream endpoint which multiplexes multiple
subscriptions over a single WebSocket. Reconnects with exponential
backoff on disconnect.

Uses Binance.US's aggTrade stream (not @trade). aggTrade aggregates
contiguous fills at the same price into a single event; it's the
practical choice for charting and most strategies. The platform-wide
TradeEvent shape is unchanged — we just use the aggregate trade ID
as venue_trade_id instead of the individual fill ID.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

import structlog
import websockets

from packages.adapters.base import AssetAdapter
from packages.adapters.crypto import _symbols
from packages.core.exceptions import AdapterError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide

if TYPE_CHECKING:
    from packages.data.symbol_registry import SymbolRegistry

log = structlog.get_logger(__name__)

WS_BASE = "wss://stream.binance.us:9443/stream"

# Max combined-stream subscriptions per WebSocket connection. Binance allows up
# to 1024 but very long URLs are fragile; we chunk well below that. Each pair
# uses 1 stream for trades (and 1 more for L1 quotes if enabled).
MAX_STREAMS_PER_CONN = 100


class BinanceUSAdapter(AssetAdapter):
    """Adapter for Binance.US spot trade and L1 quote streams.

    Native<->canonical translation comes from an injected ``SymbolRegistry``
    (loaded from the instruments table) so the universe is not capped to a
    hardcoded list. When no registry is provided (e.g. unit tests), it falls
    back to mechanical symbol splitting via :mod:`packages.adapters.crypto._symbols`.
    """

    venue = "BINANCEUS"

    def __init__(self, registry: "SymbolRegistry | None" = None) -> None:
        self._registry = registry

    def to_native_symbol(self, canonical_symbol: str) -> str:
        """'BTC-USDT@BINANCEUS' -> 'BTCUSDT'."""
        if "@" not in canonical_symbol:
            raise AdapterError(
                f"canonical symbol missing venue suffix: {canonical_symbol}"
            )
        symbol_part, venue = canonical_symbol.split("@", 1)
        if venue != self.venue:
            raise AdapterError(
                f"venue mismatch: {venue} (expected {self.venue})"
            )
        return symbol_part.replace("-", "")

    def to_canonical_symbol(self, native_symbol: str) -> str:
        """'BTCUSDT' -> 'BTC-USDT@BINANCEUS'.

        Prefers the injected registry (exact, instruments-backed); falls back
        to mechanical quote-asset splitting when no registry is available or
        the symbol is not yet in the table.
        """
        if self._registry is not None:
            canonical = self._registry.to_canonical_or_none(native_symbol, self.venue)
            if canonical is not None:
                return canonical
        try:
            return _symbols.native_to_canonical(native_symbol)
        except ValueError as e:
            raise AdapterError(str(e)) from e

    def _build_stream_url(
        self,
        native_symbols: list[str],
        stream_suffix: str,
    ) -> str:
        """Build a combined-stream URL for the given symbols and stream type."""
        parts = "/".join(
            f"{s.lower()}@{stream_suffix}" for s in native_symbols
        )
        return f"{WS_BASE}?streams={parts}"

    async def stream_trades(
        self,
        canonical_symbols: list[str],
    ) -> AsyncIterator[TradeEvent]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        async for event in self._stream_chunked(native, "aggTrade", self._parse_trade):
            yield event

    async def stream_quotes_l1(
        self,
        canonical_symbols: list[str],
    ) -> AsyncIterator[QuoteL1Event]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        async for event in self._stream_chunked(native, "bookTicker", self._parse_quote):
            yield event

    async def _stream_chunked(
        self,
        native_symbols: list[str],
        stream_suffix: str,
        parser: Callable[[dict[str, Any]], Any],
    ) -> AsyncIterator[Any]:
        """Stream from one or more WS connections, chunked to respect the
        per-connection stream cap. A single chunk streams directly; multiple
        chunks each run an independent reconnect loop and fan in via a queue.
        """
        chunks = [
            native_symbols[i : i + MAX_STREAMS_PER_CONN]
            for i in range(0, len(native_symbols), MAX_STREAMS_PER_CONN)
        ]
        if len(chunks) <= 1:
            url = self._build_stream_url(native_symbols, stream_suffix)
            async for event in self._reconnect_loop(url, parser):
                yield event
            return

        log.info(
            "binanceus.stream_sharded",
            stream=stream_suffix,
            symbols=len(native_symbols),
            connections=len(chunks),
        )
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=10000)

        async def _pump(chunk: list[str]) -> None:
            url = self._build_stream_url(chunk, stream_suffix)
            async for event in self._reconnect_loop(url, parser):
                await queue.put(event)

        tasks = [asyncio.create_task(_pump(c)) for c in chunks]
        try:
            while True:
                yield await queue.get()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reconnect_loop(
        self,
        url: str,
        parser: Callable[[dict[str, Any]], Any],
    ) -> AsyncIterator[Any]:
        """Run the WS connection with exponential-backoff reconnect.

        Yields parsed events. Catches transient errors internally; lets
        unexpected exceptions propagate.
        """
        backoff = 1
        while True:
            try:
                log.info("binanceus.connecting", url=url, backoff=backoff)
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20
                ) as ws:
                    log.info("binanceus.connected", url=url)
                    backoff = 1  # reset on successful connect
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            event = parser(msg)
                            if event is not None:
                                yield event
                        except Exception as e:
                            log.warning(
                                "binanceus.parse_error",
                                error=str(e),
                                raw=raw[:200] if isinstance(raw, str) else "<bytes>",
                            )
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning(
                    "binanceus.disconnected",
                    error=str(e),
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _parse_trade(self, msg: dict[str, Any]) -> TradeEvent | None:
        """Parse a Binance.US aggTrade WebSocket message into a TradeEvent.

        Combined-stream format wraps the payload:
            {"stream": "btcusdt@aggTrade", "data": {...}}
        The aggTrade event in `data` has these fields we use:
            e: event type ("aggTrade")
            E: event time (epoch ms)
            s: symbol ("BTCUSDT")
            a: aggregate trade ID
            p: price (string)
            q: aggregated quantity (string)
            T: trade time (epoch ms)
            m: was the buyer the market maker? (true = seller-initiated)
            f, l: first/last individual trade IDs in this aggregation (unused)
        """
        data = msg.get("data")
        if not data or data.get("e") != "aggTrade":
            return None

        ts = datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc)

        # When 'm' (is buyer maker) is True, the aggressor was the SELLER.
        side = TradeSide.SELL if data.get("m") else TradeSide.BUY

        return TradeEvent(
            canonical_symbol=self.to_canonical_symbol(data["s"]),
            ts=ts,
            price=Decimal(data["p"]),
            quantity=Decimal(data["q"]),
            side=side,
            venue_trade_id=str(data["a"]),
        )

    def _parse_quote(self, msg: dict[str, Any]) -> QuoteL1Event | None:
        """Parse a Binance.US bookTicker message into a QuoteL1Event.

        Combined-stream format:
            {"stream": "btcusdt@bookTicker", "data": {...}}
        Fields used:
            s: symbol
            b: best bid price (string)
            B: best bid quantity (string)
            a: best ask price (string)
            A: best ask quantity (string)

        bookTicker messages do not include a timestamp, so we record
        ingestion time as the canonical ts.
        """
        data = msg.get("data")
        if not data or "s" not in data:
            return None

        return QuoteL1Event(
            canonical_symbol=self.to_canonical_symbol(data["s"]),
            ts=datetime.now(tz=timezone.utc),
            bid=Decimal(data["b"]),
            bid_size=Decimal(data["B"]),
            ask=Decimal(data["a"]),
            ask_size=Decimal(data["A"]),
        )
