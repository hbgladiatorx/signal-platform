"""Alpaca equity ingestion service.

Streams US-equity trades from Alpaca's market-data v2 WebSocket and publishes
canonical TradeEvents to trades:raw, so the existing bar_builder → caggs
pipeline produces equity bars exactly like crypto.

Configuration via environment:
    ALPACA_DATA_KEY_ID      platform Alpaca market-data key
    ALPACA_DATA_SECRET      platform Alpaca market-data secret
    ALPACA_DATA_FEED        "iex" (free, 1 connection) | "sip" (default iex)
    INGESTION_ALPACA_SYMBOLS  comma-separated canonical symbols (AAPL@ALPACA,…)
    ALPACA_INGEST_QUOTES    "1" to also stream L1 quotes (needs a 2nd
                            connection; not available on the free iex plan)
    REDIS_URL, LOG_LEVEL

Run:  python -m services.ingestion_alpaca.main
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import orjson
import structlog

from packages.adapters.equity.alpaca import AlpacaDataAdapter
from packages.core.exceptions import ConfigError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.data.messagebus import (
    STREAM_QUOTES_RAW,
    STREAM_TRADES_RAW,
    RedisStreamsBus,
)


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level, logging.INFO)
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


class AlpacaIngestionService:
    def __init__(self, symbols: list[str], *, stream_quotes: bool) -> None:
        if not symbols:
            raise ConfigError("INGESTION_ALPACA_SYMBOLS resolved to an empty list")
        key = os.environ.get("ALPACA_DATA_KEY_ID", "")
        secret = os.environ.get("ALPACA_DATA_SECRET", "")
        feed = os.environ.get("ALPACA_DATA_FEED", "iex")
        if not key or not secret:
            raise ConfigError("ALPACA_DATA_KEY_ID / ALPACA_DATA_SECRET not set")
        self.symbols = symbols
        self.stream_quotes = stream_quotes
        self.adapter = AlpacaDataAdapter(key, secret, feed=feed)
        self.bus = RedisStreamsBus()
        self._shutdown = asyncio.Event()
        self._trade_count = 0
        self._quote_count = 0

    async def run(self) -> None:
        log.info("ingestion.starting", source="alpaca", symbols=self.symbols,
                 quotes=self.stream_quotes)
        tasks = [
            asyncio.create_task(self._run_trades(), name="trades"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
        if self.stream_quotes:
            tasks.append(asyncio.create_task(self._run_quotes(), name="quotes"))
        await self._shutdown.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.bus.close()
        log.info("ingestion.stopped", source="alpaca")

    async def _run_trades(self) -> None:
        try:
            async for event in self.adapter.stream_trades(self.symbols):
                await self._publish(STREAM_TRADES_RAW, event)
                self._trade_count += 1
        except asyncio.CancelledError:
            raise

    async def _run_quotes(self) -> None:
        try:
            async for event in self.adapter.stream_quotes_l1(self.symbols):
                await self._publish(STREAM_QUOTES_RAW, event)
                self._quote_count += 1
        except asyncio.CancelledError:
            raise

    async def _publish(self, stream: str, event: TradeEvent | QuoteL1Event) -> None:
        try:
            await self.bus.publish(stream, event.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001
            log.error("ingestion.publish_failed", stream=stream, error=str(e))

    async def _heartbeat(self) -> None:
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                log.info("ingestion.heartbeat", source="alpaca",
                         trades_1m=self._trade_count, quotes_1m=self._quote_count,
                         ts=datetime.now(timezone.utc).isoformat())
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


async def amain() -> None:
    _configure_logging()
    symbols_env = os.environ.get("INGESTION_ALPACA_SYMBOLS", "")
    symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    if not symbols:
        # Idle instead of exiting so the container stays healthy rather than
        # crash-looping under `restart: unless-stopped`. A restart once the
        # equity universe is configured picks up INGESTION_ALPACA_SYMBOLS.
        log.warning("ingestion.idle_no_symbols", source="alpaca")
        await _idle_until_signal()
        return
    stream_quotes = os.environ.get("ALPACA_INGEST_QUOTES", "0") == "1"
    service = AlpacaIngestionService(symbols=symbols, stream_quotes=stream_quotes)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, service.shutdown)

    try:
        await service.run()
    except Exception as e:
        log.exception("ingestion.fatal", source="alpaca", error=str(e))
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(amain())
