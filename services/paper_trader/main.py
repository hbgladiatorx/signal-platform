"""Paper-trading runner service.

Runs strategies live against the bars:closed stream and routes orders to users'
Alpaca *paper* accounts. One process multiplexes many sessions (see
packages.livetrade.runner.PaperTrader). Scale out with SHARD_INDEX/SHARD_COUNT.

Mirrors services/backtest_worker for logging, engine, and graceful SIGTERM.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal as signal_module
import sys
from pathlib import Path

import structlog

from packages.data.db import get_engine
from packages.data.messagebus import RedisStreamsBus
from packages.livetrade.runner import PaperTrader
from packages.strategy.registry import discover_strategies


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


_configure_logging()
log = structlog.get_logger(__name__)

WORKER_NAME = os.environ.get("HOSTNAME", "paper-trader-1")
SHARD_INDEX = int(os.environ.get("SHARD_INDEX", "0"))
SHARD_COUNT = int(os.environ.get("SHARD_COUNT", "1"))
STRATEGIES_DIR = Path(os.environ.get("STRATEGIES_DIR", "/app/strategies"))


async def main_loop() -> None:
    engine = get_engine()
    bus = RedisStreamsBus()
    builtin_registry = discover_strategies(STRATEGIES_DIR)

    trader = PaperTrader(
        bus=bus,
        engine=engine,
        builtin_registry=builtin_registry,
        worker_name=WORKER_NAME,
        shard_index=SHARD_INDEX,
        shard_count=SHARD_COUNT,
    )

    log.info(
        "paper_trader.starting",
        worker=WORKER_NAME,
        shard=f"{SHARD_INDEX}/{SHARD_COUNT}",
        strategies=list(builtin_registry.keys()),
    )

    loop = asyncio.get_event_loop()
    for sig in (signal_module.SIGINT, signal_module.SIGTERM):
        try:
            loop.add_signal_handler(sig, trader.stop)
        except NotImplementedError:
            pass

    try:
        await trader.run()
    finally:
        await bus.close()
        await engine.dispose()
        log.info("paper_trader.stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        sys.exit(0)
