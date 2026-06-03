"""Polygon equity (and option) ingestion service.

Streams US-equity market data from Polygon's WebSocket and publishes canonical
TradeEvents to trades:raw, so the existing bar_builder → caggs pipeline produces
equity bars exactly like crypto. Symbols carry the @ALPACA execution-venue tag
(see packages/adapters/equity/polygon.py).

Configuration via environment:
    POLYGON_API_KEY           Polygon API key
    INGESTION_POLYGON_SYMBOLS "*"/"all" for the full active equity universe from
                              the instruments table, or a comma-separated list of
                              canonical symbols (AAPL@ALPACA,...). Empty -> idle.
    INGESTION_POLYGON_CHANNEL trades | aggregates_sec (default) | aggregates_min
    INGESTION_POLYGON_CLUSTER stocks (default) | options
    INGESTION_POLYGON_ASSET_CLASS  equity (default) | option
    SHARD_INDEX / SHARD_COUNT shard this worker across the universe
    REDIS_URL, LOG_LEVEL

Run:  python -m services.ingestion_polygon.main
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import orjson
import structlog

from packages.adapters.equity.polygon import PolygonDataAdapter
from packages.core.exceptions import ConfigError
from packages.core.models import TradeEvent
from packages.data.db import dispose_engine, get_engine
from packages.data.messagebus import STREAM_TRADES_RAW, RedisStreamsBus
from packages.data.symbol_registry import SymbolRegistry


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


class PolygonIngestionService:
    def __init__(self, symbols: list[str], adapter: PolygonDataAdapter) -> None:
        if not symbols:
            raise ConfigError("Polygon ingestion resolved to an empty symbol list")
        self.symbols = symbols
        self.adapter = adapter
        self.bus = RedisStreamsBus()
        self._shutdown = asyncio.Event()
        self._trade_count = 0

    async def run(self) -> None:
        log.info(
            "ingestion.starting",
            source="polygon",
            symbol_count=len(self.symbols),
            channel=self.adapter.channel,
            cluster=self.adapter.cluster,
        )
        tasks = [
            asyncio.create_task(self._run_trades(), name="trades"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
        await self._shutdown.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.bus.close()
        log.info("ingestion.stopped", source="polygon")

    async def _run_trades(self) -> None:
        try:
            async for event in self.adapter.stream_trades(self.symbols):
                await self._publish(event)
                self._trade_count += 1
        except asyncio.CancelledError:
            raise

    async def _publish(self, event: TradeEvent) -> None:
        try:
            await self.bus.publish(STREAM_TRADES_RAW, event.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001
            log.error("ingestion.publish_failed", error=str(e))

    async def _heartbeat(self) -> None:
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                log.info(
                    "ingestion.heartbeat",
                    source="polygon",
                    trades_1m=self._trade_count,
                    ts=datetime.now(timezone.utc).isoformat(),
                )
                self._trade_count = 0
        except asyncio.CancelledError:
            raise

    def shutdown(self) -> None:
        self._shutdown.set()


def _apply_shard(symbols: list[str]) -> list[str]:
    count = int(os.environ.get("SHARD_COUNT", "1"))
    index = int(os.environ.get("SHARD_INDEX", "0"))
    if count <= 1:
        return symbols
    return [
        s
        for s in symbols
        if int(hashlib.md5(s.encode()).hexdigest(), 16) % count == index
    ]


async def _idle_until_signal() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def amain() -> None:
    _configure_logging()

    api_key = os.environ.get("POLYGON_API_KEY", "")
    channel = os.environ.get("INGESTION_POLYGON_CHANNEL", "aggregates_sec")
    cluster = os.environ.get("INGESTION_POLYGON_CLUSTER", "stocks")
    asset_class = os.environ.get("INGESTION_POLYGON_ASSET_CLASS", "equity")

    engine = get_engine()
    registry = await SymbolRegistry.load(
        engine, venue="ALPACA", asset_class=asset_class
    )

    symbols_env = os.environ.get("INGESTION_POLYGON_SYMBOLS", "").strip()
    if symbols_env.lower() in ("*", "all"):
        symbols = registry.canonicals_for_venue("ALPACA")
    else:
        symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    symbols = _apply_shard(symbols)

    if not symbols or not api_key:
        log.warning(
            "ingestion.idle_no_symbols",
            source="polygon",
            have_key=bool(api_key),
            symbol_count=len(symbols),
        )
        await dispose_engine()
        await _idle_until_signal()
        return

    adapter = PolygonDataAdapter(api_key, channel=channel, cluster=cluster)

    # Entitlement probe: detect a missing real-time plan up front. A timeout is
    # inconclusive (markets may be closed), so we only treat auth_failed as fatal
    # and otherwise proceed — the stream delivers when the market is open.
    report = await adapter.probe_entitlement(symbols[0])
    if report.get("reason") == "auth_failed":
        log.error("polygon.entitlement_auth_failed", detail=report.get("detail"))
        await dispose_engine()
        await _idle_until_signal()
        return
    log.info("polygon.entitlement_probe", **{k: v for k, v in report.items() if k != "detail"})

    service = PolygonIngestionService(symbols=symbols, adapter=adapter)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, service.shutdown)

    try:
        await service.run()
    except Exception as e:
        log.exception("ingestion.fatal", source="polygon", error=str(e))
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(amain())
