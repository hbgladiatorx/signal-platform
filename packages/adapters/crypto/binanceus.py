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
from typing import Any, Callable

import structlog
import websockets

from packages.adapters.base import AssetAdapter
from packages.adapters.crypto.binance_universe import (
    BinanceInstrument,
    build_translation_maps,
    fetch_universe,
)
from packages.core.exceptions import AdapterError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide

log = structlog.get_logger(__name__)

WS_BASE = "wss://stream.binance.us:9443/stream"

# Bootstrap translation table. Historically this was the *entire* Phase 1
# universe; it now serves only as an offline fallback for the two majors so
# the adapter keeps working before `load_universe()` runs. Once the universe
# is loaded (from exchangeInfo), the full set of TRADING pairs is available.
_NATIVE_TO_CANONICAL_FALLBACK: dict[str, str] = {
    "BTCUSDT": "BTC-USDT@BINANCEUS",
    "ETHUSDT": "ETH-USDT@BINANCEUS",
}


class BinanceUSAdapter(AssetAdapter):
    """Adapter for Binance.US spot trade and L1 quote streams.

    Symbol translation works against a loadable universe. Construct with an
    explicit ``native_to_canonical`` map, or call :meth:`load_universe` to pull
    the full Binance.US spot universe from exchangeInfo. With no universe
    loaded the adapter still resolves the two majors via the offline fallback.
    """

    venue = "BINANCEUS"

    def __init__(
        self,
        native_to_canonical: dict[str, str] | None = None,
    ) -> None:
        self._native_to_canonical: dict[str, str] = dict(
            _NATIVE_TO_CANONICAL_FALLBACK
        )
        if native_to_canonical:
            self._native_to_canonical.update(
                {k.upper(): v for k, v in native_to_canonical.items()}
            )

    def set_universe(self, universe: list[BinanceInstrument]) -> None:
        """Install a fetched universe as the translation table."""
        native_to_canonical, _ = build_translation_maps(universe)
        # Always keep the offline fallback so the majors resolve even if a
        # filtered universe excluded them.
        merged = dict(_NATIVE_TO_CANONICAL_FALLBACK)
        merged.update(native_to_canonical)
        self._native_to_canonical = merged

    async def load_universe(self, **kwargs: object) -> int:
        """Fetch the full Binance.US universe and install it.

        Returns the number of pairs loaded. Extra kwargs are forwarded to
        :func:`packages.adapters.crypto.binance_universe.fetch_universe`
        (e.g. ``quote_assets={"USDT"}``).
        """
        universe = await fetch_universe(**kwargs)  # type: ignore[arg-type]
        self.set_universe(universe)
        log.info("binanceus.universe_loaded", pairs=len(universe))
        return len(universe)

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

        Resolves against the loaded universe; falls back to the offline table
        for the majors. Unknown symbols raise AdapterError.
        """
        key = native_symbol.upper()
        canonical = self._native_to_canonical.get(key)
        if canonical is None:
            raise AdapterError(
                f"unknown native symbol: {native_symbol} "
                f"(load_universe() may be required)"
            )
        return canonical

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
        url = self._build_stream_url(native, "aggTrade")
        async for event in self._reconnect_loop(url, self._parse_trade):
            yield event

    async def stream_quotes_l1(
        self,
        canonical_symbols: list[str],
    ) -> AsyncIterator[QuoteL1Event]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        url = self._build_stream_url(native, "bookTicker")
        async for event in self._reconnect_loop(url, self._parse_quote):
            yield event

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
