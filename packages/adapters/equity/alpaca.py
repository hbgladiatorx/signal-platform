"""Alpaca equity market-data adapter (AssetAdapter).

Streams US-equity trades (and optionally L1 quotes) from Alpaca's market-data
v2 WebSocket and emits canonical platform events, so the existing pipeline
(trades:raw → bar_builder → caggs) builds equity bars with zero changes.

Endpoint: wss://stream.data.alpaca.markets/v2/{feed}
  feed = "iex" (free, 1 concurrent connection) or "sip" (paid).
Protocol is JSON: auth {"action":"auth","key","secret"} → subscribe
{"action":"subscribe","trades":[...]} → arrays of {"T":"t",...} messages.

Symbol mapping: canonical 'AAPL@ALPACA' <-> native 'AAPL'.

NOTE on connections: the free iex feed permits a single concurrent connection,
so the ingestion service subscribes trades only (all the bar pipeline needs).
stream_quotes_l1 is implemented for sip/paid use but should not be run
concurrently with stream_trades on a single-connection plan.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
import websockets

from packages.adapters.base import AssetAdapter
from packages.core.exceptions import AdapterError, ConfigError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.core.types import TradeSide

log = structlog.get_logger(__name__)

DATA_WS_BASE = "wss://stream.data.alpaca.markets/v2"


class AlpacaDataAdapter(AssetAdapter):
    """Adapter for Alpaca US-equity trade and L1 quote streams."""

    venue = "ALPACA"

    def __init__(
        self, api_key_id: str, secret_key: str, *, feed: str = "iex"
    ) -> None:
        if not api_key_id or not secret_key:
            raise ConfigError("AlpacaDataAdapter requires api_key_id and secret_key")
        self._key = api_key_id
        self._secret = secret_key
        self._feed = feed
        self._url = f"{DATA_WS_BASE}/{feed}"

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

    # --- Streams ---
    async def stream_trades(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[TradeEvent]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        async for ev in self._run(
            subscribe={"trades": native}, parser=self._parse_trade
        ):
            yield ev

    async def stream_quotes_l1(
        self, canonical_symbols: list[str]
    ) -> AsyncIterator[QuoteL1Event]:
        native = [self.to_native_symbol(s) for s in canonical_symbols]
        async for ev in self._run(
            subscribe={"quotes": native}, parser=self._parse_quote
        ):
            yield ev

    async def _run(
        self,
        subscribe: dict[str, list[str]],
        parser: Callable[[dict[str, Any]], Any],
    ) -> AsyncIterator[Any]:
        backoff = 1
        while True:
            try:
                log.info("alpaca_data.connecting", url=self._url, sub=subscribe)
                async with websockets.connect(
                    self._url, ping_interval=20, ping_timeout=20
                ) as ws:
                    await ws.send(
                        json.dumps(
                            {"action": "auth", "key": self._key, "secret": self._secret}
                        )
                    )
                    await ws.send(json.dumps({"action": "subscribe", **subscribe}))
                    log.info("alpaca_data.subscribed", sub=subscribe)
                    backoff = 1
                    async for raw in ws:
                        for msg in _frames(raw):
                            mt = msg.get("T")
                            if mt in ("success", "subscription"):
                                continue
                            if mt == "error":
                                log.error("alpaca_data.error", msg=msg)
                                # auth/subscription errors are fatal → surface
                                if msg.get("code") in (401, 402, 403, 404, 406, 409):
                                    raise AdapterError(f"Alpaca data error: {msg}")
                                continue
                            try:
                                event = parser(msg)
                            except Exception as e:  # noqa: BLE001
                                log.warning("alpaca_data.parse_error", error=str(e))
                                continue
                            if event is not None:
                                yield event
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("alpaca_data.disconnected", error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _parse_trade(self, msg: dict[str, Any]) -> TradeEvent | None:
        if msg.get("T") != "t":
            return None
        return TradeEvent(
            canonical_symbol=self.to_canonical_symbol(msg["S"]),
            ts=_parse_ts(msg.get("t")),
            price=Decimal(str(msg["p"])),
            quantity=Decimal(str(msg["s"])),
            # Equity trade prints carry no aggressor side; default buy. Bars are
            # built from price/volume, so side is not material here.
            side=TradeSide.BUY,
            venue_trade_id=str(msg.get("i", "")),
        )

    def _parse_quote(self, msg: dict[str, Any]) -> QuoteL1Event | None:
        if msg.get("T") != "q":
            return None
        return QuoteL1Event(
            canonical_symbol=self.to_canonical_symbol(msg["S"]),
            ts=_parse_ts(msg.get("t")),
            bid=Decimal(str(msg.get("bp", 0))),
            bid_size=Decimal(str(msg.get("bs", 0))),
            ask=Decimal(str(msg.get("ap", 0))),
            ask_size=Decimal(str(msg.get("as", 0))),
        )


def _frames(raw: Any) -> list[dict[str, Any]]:
    """Alpaca sends a JSON array of messages per frame."""
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _parse_ts(v: Any) -> datetime:
    """Parse Alpaca RFC3339 timestamps, which carry nanosecond (9-digit)
    precision that datetime.fromisoformat won't accept — truncate to micros."""
    if not v:
        return datetime.now(tz=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    # Truncate fractional seconds to 6 digits if longer (nanos → micros).
    if "." in s:
        head, _, tail = s.partition(".")
        digits = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[i:]
                break
        s = f"{head}.{digits[:6]}{rest}"
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(tz=timezone.utc)
