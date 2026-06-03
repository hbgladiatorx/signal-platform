"""Polygon.io market-data adapter (AssetAdapter).

Streams US-equity (and, with the options cluster, single-leg option) market data
from Polygon's WebSocket and emits canonical platform events, so the existing
pipeline (trades:raw → bar_builder → caggs) builds bars with zero changes.

Canonical form keeps the EXECUTION venue tag (``AAPL@ALPACA``) even though the
data comes from Polygon — orders for that symbol route to Alpaca, and we want
one instrument row / one bar series shared between Polygon data and Alpaca
execution. The data source is recorded in ``instruments.metadata.data_source``.

Channels (firehose control):
  - "trades"          -> T.*  : one TradeEvent per print (heaviest)
  - "aggregates_sec"  -> A.*  : one TradeEvent per 1s aggregate at close price
                                (DEFAULT — Polygon aggregates server-side,
                                collapsing the full-universe firehose ~50-100x)
  - "aggregates_min"  -> AM.* : one TradeEvent per 1m aggregate (lightest)

Endpoints:
  stocks  -> wss://socket.polygon.io/stocks
  options -> wss://socket.polygon.io/options   (used by the options workstream)
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import structlog
import websockets

from packages.adapters.base import AssetAdapter
from packages.core.exceptions import AdapterError, ConfigError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide

log = structlog.get_logger(__name__)

Channel = Literal["trades", "aggregates_sec", "aggregates_min"]
Cluster = Literal["stocks", "options"]

_CLUSTER_URL = {
    "stocks": "wss://socket.polygon.io/stocks",
    "options": "wss://socket.polygon.io/options",
}
# channel -> (subscribe prefix, websocket event tag)
_CHANNEL_SPEC: dict[str, tuple[str, str]] = {
    "trades": ("T", "T"),
    "aggregates_sec": ("A", "A"),
    "aggregates_min": ("AM", "AM"),
}


class PolygonDataAdapter(AssetAdapter):
    """Adapter for Polygon US-equity / option market-data streams."""

    venue = "ALPACA"  # execution venue tag carried by canonical symbols

    def __init__(
        self,
        api_key: str,
        *,
        channel: Channel = "aggregates_sec",
        cluster: Cluster = "stocks",
    ) -> None:
        if not api_key:
            raise ConfigError("PolygonDataAdapter requires a Polygon API key")
        if channel not in _CHANNEL_SPEC:
            raise ConfigError(f"unknown Polygon channel: {channel}")
        self._key = api_key
        self.channel = channel
        self.cluster = cluster
        self._url = _CLUSTER_URL[cluster]
        self._prefix, self._ev = _CHANNEL_SPEC[channel]

    # --- Symbol translation ---
    def to_native_symbol(self, canonical_symbol: str) -> str:
        if "@" not in canonical_symbol:
            raise AdapterError(
                f"canonical symbol missing venue suffix: {canonical_symbol}"
            )
        sym, venue = canonical_symbol.split("@", 1)
        if venue != self.venue:
            raise AdapterError(f"venue mismatch: {venue} (expected {self.venue})")
        return sym

    def to_canonical_symbol(self, native_symbol: str) -> str:
        return f"{native_symbol.upper()}@{self.venue}"

    def _native_to_polygon_ticker(self, native: str) -> str:
        """Equity tickers pass through; options use the O:OCC form on the wire."""
        if self.cluster == "options" and not native.startswith("O:"):
            return f"O:{native}"
        return native

    def _polygon_ticker_to_native(self, ticker: str) -> str:
        return ticker[2:] if ticker.startswith("O:") else ticker

    # --- Streams ---
    async def stream_trades(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[TradeEvent]:
        params = ",".join(
            f"{self._prefix}.{self._native_to_polygon_ticker(self.to_native_symbol(s))}"
            for s in canonical_symbols
        )
        async for ev in self._run(params, self._parse_trade):
            yield ev

    async def stream_quotes_l1(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[QuoteL1Event]:
        params = ",".join(
            f"Q.{self._native_to_polygon_ticker(self.to_native_symbol(s))}"
            for s in canonical_symbols
        )
        async for ev in self._run(params, self._parse_quote):
            yield ev

    async def _run(
        self,
        sub_params: str,
        parser: Callable[[dict[str, Any]], Any],
    ) -> AsyncIterator[Any]:
        backoff = 1
        while True:
            try:
                log.info("polygon.connecting", url=self._url, channel=self.channel)
                async with websockets.connect(
                    self._url, ping_interval=20, ping_timeout=20, max_size=2**22
                ) as ws:
                    await self._auth_and_subscribe(ws, sub_params)
                    backoff = 1
                    async for raw in ws:
                        for msg in _frames(raw):
                            ev = msg.get("ev")
                            if ev == "status":
                                if msg.get("status") in ("auth_failed", "error"):
                                    log.error("polygon.status_error", msg=msg)
                                    if msg.get("status") == "auth_failed":
                                        raise AdapterError(f"Polygon auth failed: {msg}")
                                continue
                            try:
                                parsed = parser(msg)
                            except Exception as e:  # noqa: BLE001
                                log.warning("polygon.parse_error", error=str(e))
                                continue
                            if parsed is not None:
                                yield parsed
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("polygon.disconnected", error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _auth_and_subscribe(self, ws: Any, sub_params: str) -> None:
        await ws.send(json.dumps({"action": "auth", "params": self._key}))
        # Chunk large subscriptions (full-universe lists can be thousands of
        # tickers) into multiple subscribe messages on the same connection.
        params = sub_params.split(",")
        chunk = 1000
        for i in range(0, len(params), chunk):
            await ws.send(
                json.dumps(
                    {"action": "subscribe", "params": ",".join(params[i : i + chunk])}
                )
            )
        log.info("polygon.subscribed", channel=self.channel, params_count=len(params))

    # --- Parsers ---
    def _parse_trade(self, msg: dict[str, Any]) -> TradeEvent | None:
        ev = msg.get("ev")
        if ev != self._ev:
            return None
        sym = msg.get("sym")
        if not sym:
            return None
        native = self._polygon_ticker_to_native(sym)
        canonical = self.to_canonical_symbol(native)
        if ev == "T":
            return TradeEvent(
                canonical_symbol=canonical,
                ts=_ms_to_dt(msg.get("t")),
                price=Decimal(str(msg["p"])),
                quantity=Decimal(str(msg.get("s", 0))),
                side=TradeSide.BUY,  # prints carry no aggressor; bars use price/vol
                venue_trade_id=str(msg.get("i", "")),
            )
        # Aggregate (A / AM): synthesize one trade at the bar's close.
        end_ms = msg.get("e") or msg.get("s")
        return TradeEvent(
            canonical_symbol=canonical,
            ts=_ms_to_dt(end_ms),
            price=Decimal(str(msg["c"])),
            quantity=Decimal(str(msg.get("v", 0))),
            side=TradeSide.BUY,
            venue_trade_id=f"agg-{self._ev}-{end_ms}",
        )

    def _parse_quote(self, msg: dict[str, Any]) -> QuoteL1Event | None:
        if msg.get("ev") != "Q":
            return None
        sym = msg.get("sym")
        if not sym:
            return None
        native = self._polygon_ticker_to_native(sym)
        return QuoteL1Event(
            canonical_symbol=self.to_canonical_symbol(native),
            ts=_ms_to_dt(msg.get("t")),
            bid=Decimal(str(msg.get("bp", 0))),
            bid_size=Decimal(str(msg.get("bs", 0))),
            ask=Decimal(str(msg.get("ap", 0))),
            ask_size=Decimal(str(msg.get("as", 0))),
        )

    # --- Entitlement probe ---
    async def probe_entitlement(
        self, sample_canonical: str, *, timeout_s: float = 12.0
    ) -> dict[str, Any]:
        """Connect, auth, and subscribe to a single symbol on the configured
        channel; report whether data arrives. Used by the ingestion service to
        detect a missing real-time entitlement and downgrade gracefully."""
        native = self._native_to_polygon_ticker(self.to_native_symbol(sample_canonical))
        params = f"{self._prefix}.{native}"
        try:
            async with websockets.connect(
                self._url, ping_interval=20, ping_timeout=20, max_size=2**22
            ) as ws:
                await self._auth_and_subscribe(ws, params)
                deadline = asyncio.get_event_loop().time() + timeout_s
                while asyncio.get_event_loop().time() < deadline:
                    remaining = deadline - asyncio.get_event_loop().time()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    for msg in _frames(raw):
                        if msg.get("ev") == "status" and msg.get("status") == "auth_failed":
                            return {"ok": False, "reason": "auth_failed", "detail": msg}
                        if msg.get("ev") == self._ev:
                            return {"ok": True, "reason": "data_received"}
                return {"ok": False, "reason": "no_data_within_timeout"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "connect_error", "detail": str(e)}


def _frames(raw: Any) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _ms_to_dt(v: Any) -> datetime:
    if v is None:
        return datetime.now(tz=timezone.utc)
    return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
