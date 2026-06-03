"""Polygon.io ingestion service.

Subscribes to trades and L1 (NBBO) quotes for the configured equities and
publishes canonical events to the Redis message bus — the same streams the
Binance.US ingester uses, so persistence, bar building, and the live websocket
all work unchanged for Polygon symbols.

Configuration via environment:
    POLYGON_INGESTION_SYMBOLS  comma-separated canonical symbols
                               (e.g. AAPL-USD@POLYGON,MSFT-USD@POLYGON)
    POLYGON_API_KEY            Polygon API key
    REDIS_URL                  Redis connection URL
    LOG_LEVEL                  INFO / DEBUG / WARNING (default INFO)

Run:
    python -m services.ingestion_polygon.main
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone

import orjson
import structlog

from packages.adapters.equity.polygon import PolygonAdapter
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


class PolygonIngestionService:
    """Coordinates Polygon trade and quote subscription tasks."""

    def __init__(self, symbols: list[str]) -> None:
        if not symbols:
            raise ConfigError("POLYGON_INGESTION_SYMBOLS resolved to an empty list")
        self.symbols = symbols
        self.adapter = PolygonAdapter()
        self.bus = RedisStreamsBus()
        self._shutdown = asyncio.Event()
        self._trade_count = 0
        self._quote_count = 0

    async def run(self) -> None:
        log.info("ingestion.starting", source="polygon", symbols=self.symbols)
        tasks = [
            asyncio.create_task(self._run_trades(), name="trades"),
            asyncio.create_task(self._run_quotes(), name="quotes"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
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
                await self._publish(STREAM_TRADES_RAW, event)
                self._trade_count += 1
        except asyncio.CancelledError:
            log.info("ingestion.trades_cancelled")
            raise

    async def _run_quotes(self) -> None:
        try:
            async for event in self.adapter.stream_quotes_l1(self.symbols):
                await self._publish(STREAM_QUOTES_RAW, event)
                self._quote_count += 1
        except asyncio.CancelledError:
            log.info("ingestion.quotes_cancelled")
            raise

    async def _publish(
        self, stream: str, event: TradeEvent | QuoteL1Event
    ) -> None:
        try:
            await self.bus.publish(stream, event.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001
            log.error("ingestion.publish_failed", stream=stream, error=str(e))

    async def _heartbeat(self) -> None:
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                log.info(
                    "ingestion.heartbeat",
                    source="polygon",
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


async def amain() -> None:
    _configure_logging()

    symbols_env = os.environ.get("POLYGON_INGESTION_SYMBOLS", "")
    symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    if not symbols:
        log.error("ingestion.no_symbols_configured")
        sys.exit(1)

    service = PolygonIngestionService(symbols=symbols)

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
