"""Binance.US ingestion service.

Subscribes to trades and L1 quotes for the configured instruments and
publishes canonical events to the Redis message bus.

Configuration via environment:
    INGESTION_SYMBOLS  comma-separated canonical symbols, or "*"/"all" to stream
                       the entire active Binance.US universe from the
                       instruments table
    SHARD_INDEX        this worker's shard index (default 0)
    SHARD_COUNT        total number of ingestion shards (default 1)
    REDIS_URL          Redis connection URL
    LOG_LEVEL          INFO / DEBUG / WARNING (default INFO)

Run:
    python -m services.ingestion_binanceus.main
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import orjson
import structlog

from packages.adapters.crypto.binanceus import BinanceUSAdapter
from packages.core.exceptions import ConfigError
from packages.data.db import dispose_engine, get_engine
from packages.core.models import QuoteL1Event, TradeEvent
from packages.data.messagebus import (
    STREAM_QUOTES_RAW,
    STREAM_TRADES_RAW,
    RedisStreamsBus,
)
from packages.data.symbol_registry import SymbolRegistry


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), level, 20)
        ),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(
                serializer=lambda d, **k: orjson.dumps(d).decode()
            ),
        ],
    )


log = structlog.get_logger(__name__)


class IngestionService:
    """Coordinates Binance.US trade and quote subscription tasks."""

    def __init__(
        self,
        symbols: list[str],
        registry: SymbolRegistry | None = None,
        *,
        stream_quotes: bool = True,
    ) -> None:
        if not symbols:
            raise ConfigError("INGESTION_SYMBOLS resolved to an empty list")
        self.symbols = symbols
        self.stream_quotes = stream_quotes
        self.adapter = BinanceUSAdapter(registry=registry)
        self.bus = RedisStreamsBus()
        self._shutdown = asyncio.Event()
        self._trade_count = 0
        self._quote_count = 0

    async def run(self) -> None:
        log.info(
            "ingestion.starting",
            source="binanceus",
            symbol_count=len(self.symbols),
            quotes=self.stream_quotes,
        )
        tasks = [
            asyncio.create_task(self._run_trades(), name="trades"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
        if self.stream_quotes:
            tasks.append(asyncio.create_task(self._run_quotes(), name="quotes"))
        await self._shutdown.wait()
        log.info("ingestion.shutdown_requested")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.bus.close()
        log.info("ingestion.stopped")

    async def _run_trades(self) -> None:
        try:
            async for event in self.adapter.stream_trades(self.symbols):
                await self._publish_trade(event)
                self._trade_count += 1
        except asyncio.CancelledError:
            log.info("ingestion.trades_cancelled")
            raise

    async def _run_quotes(self) -> None:
        try:
            async for event in self.adapter.stream_quotes_l1(self.symbols):
                await self._publish_quote(event)
                self._quote_count += 1
        except asyncio.CancelledError:
            log.info("ingestion.quotes_cancelled")
            raise

    async def _publish_trade(self, event: TradeEvent) -> None:
        try:
            payload = event.model_dump(mode="json")
            await self.bus.publish(STREAM_TRADES_RAW, payload)
        except Exception as e:
            log.error(
                "ingestion.publish_failed",
                stream=STREAM_TRADES_RAW,
                error=str(e),
            )

    async def _publish_quote(self, event: QuoteL1Event) -> None:
        try:
            payload = event.model_dump(mode="json")
            await self.bus.publish(STREAM_QUOTES_RAW, payload)
        except Exception as e:
            log.error(
                "ingestion.publish_failed",
                stream=STREAM_QUOTES_RAW,
                error=str(e),
            )

    async def _heartbeat(self) -> None:
        """Log message-count stats every 60 seconds."""
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                log.info(
                    "ingestion.heartbeat",
                    source="binanceus",
                    trades_1m=self._trade_count,
                    quotes_1m=self._quote_count,
                    ts=datetime.now(timezone.utc).isoformat(),
                )
                self._trade_count = 0
                self._quote_count = 0
        except asyncio.CancelledError:
            raise

    def shutdown(self) -> None:
        self._shutdown.set()


async def _idle_until_signal() -> None:
    """Block until SIGINT/SIGTERM so an unconfigured service stays healthy
    and shuts down cleanly under `docker stop` (no crash-loop)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


def _apply_shard(symbols: list[str]) -> list[str]:
    """Keep only the symbols owned by this shard (stable md5 hash, not the
    salted built-in hash() which differs across processes)."""
    count = int(os.environ.get("SHARD_COUNT", "1"))
    index = int(os.environ.get("SHARD_INDEX", "0"))
    if count <= 1:
        return symbols
    return [
        s
        for s in symbols
        if int(hashlib.md5(s.encode()).hexdigest(), 16) % count == index
    ]


async def amain() -> None:
    _configure_logging()

    # Always load the registry so the adapter can canonicalize any pair in the
    # universe (not just a hardcoded handful).
    engine = get_engine()
    registry = await SymbolRegistry.load(engine, venue="BINANCEUS")

    symbols_env = os.environ.get("INGESTION_SYMBOLS", "").strip()
    if symbols_env.lower() in ("*", "all"):
        symbols = registry.canonicals_for_venue("BINANCEUS")
        log.info("ingestion.universe_from_registry", source="binanceus", count=len(symbols))
    else:
        symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]

    symbols = _apply_shard(symbols)

    if not symbols:
        # Nothing to stream (no universe configured, or this shard owns no
        # symbols). Idle and stay healthy rather than crash-loop.
        log.warning(
            "ingestion.idle_no_symbols",
            source="binanceus",
            shard_index=os.environ.get("SHARD_INDEX", "0"),
            shard_count=os.environ.get("SHARD_COUNT", "1"),
        )
        await dispose_engine()
        await _idle_until_signal()
        return

    # L1 quotes are a firehose at universe scale, so default them OFF when
    # streaming the whole universe; keep them ON for an explicit small list
    # (preserves prior behavior). Override with INGESTION_BINANCEUS_QUOTES.
    quotes_default = "0" if symbols_env.lower() in ("*", "all") else "1"
    stream_quotes = (
        os.environ.get("INGESTION_BINANCEUS_QUOTES", quotes_default) == "1"
    )
    service = IngestionService(
        symbols=symbols, registry=registry, stream_quotes=stream_quotes
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, service.shutdown)

    try:
        await service.run()
    except Exception as e:
        log.exception("ingestion.fatal", error=str(e))
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(amain())
