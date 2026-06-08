"""Persistence worker.

Consumes raw trade and quote events from Redis Streams and batches
them into TimescaleDB. Implements at-least-once delivery via
ON CONFLICT DO NOTHING on the database side.

Configuration via environment:
    DATABASE_URL       Postgres connection URL
    REDIS_URL          Redis connection URL
    LOG_LEVEL          INFO / DEBUG / WARNING (default INFO)
    PERSISTENCE_BATCH_SIZE       Optional, default 500
    PERSISTENCE_BATCH_TIMEOUT_MS Optional, default 500

Run:
    python -m services.persistence_worker.main
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import orjson
import structlog
from sqlalchemy import text

from packages.core.exceptions import ConfigError
from packages.core.models import QuoteL1Event, TradeEvent
from packages.data.db import dispose_engine, session_scope
from packages.data.messagebus import (
    GROUP_PERSISTENCE,
    STREAM_QUOTES_RAW,
    STREAM_TRADES_RAW,
    RedisStreamsBus,
)


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(
                serializer=lambda d, **k: orjson.dumps(d).decode()
            ),
        ],
    )


log = structlog.get_logger(__name__)


# ============================================================
# Worker
# ============================================================


class PersistenceWorker:
    """Consumes Redis Streams and writes to TimescaleDB.

    One worker process runs three concurrent tasks: trades, quotes,
    and heartbeat. Each consume loop maintains its own buffer and
    flushes on batch size or timeout.
    """

    def __init__(self) -> None:
        self.consumer_name = f"persistence-{socket.gethostname()}"
        self.batch_size = int(os.environ.get("PERSISTENCE_BATCH_SIZE", "500"))
        self.batch_timeout_ms = int(
            os.environ.get("PERSISTENCE_BATCH_TIMEOUT_MS", "500")
        )
        self.instrument_refresh_s = int(
            os.environ.get("PERSISTENCE_INSTRUMENT_REFRESH_S", "300")
        )
        self.bus = RedisStreamsBus()
        self._shutdown = asyncio.Event()

        # Stats per minute, reset by heartbeat
        self._trades_written_1m = 0
        self._quotes_written_1m = 0
        self._errors_1m = 0

        # Instrument cache: canonical_symbol -> instrument_id
        self._instrument_cache: dict[str, int] = {}

    async def run(self) -> None:
        log.info(
            "persistence.starting",
            consumer=self.consumer_name,
            batch_size=self.batch_size,
            batch_timeout_ms=self.batch_timeout_ms,
        )

        # Load instrument lookup table once at startup (Option 1 from design)
        await self._load_instrument_cache()
        if not self._instrument_cache:
            raise ConfigError(
                "instruments table is empty; cannot persist anything"
            )

        # Ensure consumer groups exist on both streams
        await self.bus.ensure_group(STREAM_TRADES_RAW, GROUP_PERSISTENCE)
        await self.bus.ensure_group(STREAM_QUOTES_RAW, GROUP_PERSISTENCE)

        tasks = [
            asyncio.create_task(
                self._consume_loop(
                    STREAM_TRADES_RAW,
                    self._flush_trades,
                ),
                name="trades",
            ),
            asyncio.create_task(
                self._consume_loop(
                    STREAM_QUOTES_RAW,
                    self._flush_quotes,
                ),
                name="quotes",
            ),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(
                self._instrument_refresh_loop(), name="instrument_refresh"
            ),
        ]

        await self._shutdown.wait()
        log.info("persistence.shutdown_requested")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_engine()
        log.info("persistence.stopped")

    async def _load_instrument_cache(self) -> None:
        """Load the instruments table into memory.

        Rebuilds a fresh dict and swaps it in atomically (dict-reference
        assignment) so the live universe can grow without a worker restart.
        Refreshed periodically by ``_instrument_refresh_loop``.
        """
        cache: dict[str, int] = {}
        async with session_scope() as session:
            result = await session.execute(
                text("SELECT id, canonical_symbol FROM instruments WHERE active = TRUE")
            )
            for row in result:
                cache[row.canonical_symbol] = row.id

        previous = len(self._instrument_cache)
        self._instrument_cache = cache
        # Log the full symbol list only on first load; later refreshes just
        # report the delta to avoid noisy logs on a large universe.
        if previous == 0:
            log.info("persistence.instruments_loaded", count=len(cache))
        elif len(cache) != previous:
            log.info(
                "persistence.instruments_refreshed",
                count=len(cache),
                added=len(cache) - previous,
            )

    async def _instrument_refresh_loop(self) -> None:
        """Periodically reload the instrument cache so newly discovered
        instruments become persistable without restarting the worker."""
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(self.instrument_refresh_s)
                try:
                    await self._load_instrument_cache()
                except Exception as e:  # noqa: BLE001
                    log.error("persistence.instrument_refresh_error", error=str(e))
        except asyncio.CancelledError:
            raise

    async def _consume_loop(
        self,
        stream: str,
        flush_fn: Callable[[list[tuple[str, dict[str, Any]]]], Awaitable[int]],
    ) -> None:
        """Consume messages from a stream, batching writes to the DB."""
        buffer: list[tuple[str, dict[str, Any]]] = []
        last_flush_time = time.monotonic()

        try:
            while not self._shutdown.is_set():
                try:
                    messages = await self.bus.consume(
                        stream=stream,
                        group=GROUP_PERSISTENCE,
                        consumer=self.consumer_name,
                        count=self.batch_size,
                        block_ms=self.batch_timeout_ms,
                    )
                    buffer.extend(messages)
                except Exception as e:
                    log.error(
                        "persistence.consume_error",
                        stream=stream,
                        error=str(e),
                    )
                    self._errors_1m += 1
                    await asyncio.sleep(1)
                    continue

                now = time.monotonic()
                time_since_flush_ms = (now - last_flush_time) * 1000
                should_flush_by_size = len(buffer) >= self.batch_size
                should_flush_by_time = (
                    buffer and time_since_flush_ms >= self.batch_timeout_ms
                )

                if should_flush_by_size or should_flush_by_time:
                    try:
                        written = await flush_fn(buffer)
                        message_ids = [msg_id for msg_id, _ in buffer]
                        await self.bus.ack(
                            stream, GROUP_PERSISTENCE, message_ids
                        )
                        buffer.clear()
                        last_flush_time = now
                        log.debug(
                            "persistence.flushed",
                            stream=stream,
                            written=written,
                            ack_count=len(message_ids),
                        )
                    except Exception as e:
                        log.error(
                            "persistence.flush_error",
                            stream=stream,
                            buffered=len(buffer),
                            error=str(e),
                        )
                        self._errors_1m += 1
                        # Don't clear buffer; messages remain unacked
                        # and will be re-delivered on the next consume.
                        # Sleep briefly to avoid hot-looping on a sticky failure.
                        await asyncio.sleep(1)
        except asyncio.CancelledError:
            log.info("persistence.consume_cancelled", stream=stream)
            raise

    async def _flush_trades(
        self,
        batch: list[tuple[str, dict[str, Any]]],
    ) -> int:
        """Insert a batch of trade events into the trades table."""
        rows: list[dict[str, Any]] = []

        for _msg_id, payload in batch:
            try:
                event = TradeEvent.model_validate(payload)
            except Exception as e:
                log.warning(
                    "persistence.invalid_trade_payload",
                    error=str(e),
                    payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
                )
                continue

            instrument_id = self._instrument_cache.get(event.canonical_symbol)
            if instrument_id is None:
                log.warning(
                    "persistence.unknown_symbol",
                    canonical_symbol=event.canonical_symbol,
                )
                continue

            rows.append(
                {
                    "instrument_id": instrument_id,
                    "ts": event.ts,
                    "price": event.price,
                    "quantity": event.quantity,
                    "side": event.side.value if event.side else None,
                    "venue_trade_id": event.venue_trade_id,
                }
            )

        if not rows:
            return 0

        # Use Postgres COPY-style bulk insert. ON CONFLICT keyed on the
        # composite primary key (instrument_id, ts, venue_trade_id) means
        # redelivered messages are silently ignored.
        async with session_scope() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO trades
                        (instrument_id, ts, price, quantity, side, venue_trade_id)
                    VALUES
                        (:instrument_id, :ts, :price, :quantity, :side, :venue_trade_id)
                    ON CONFLICT (instrument_id, ts, venue_trade_id) DO NOTHING
                    """
                ),
                rows,
            )

        self._trades_written_1m += len(rows)
        return len(rows)

    async def _flush_quotes(
        self,
        batch: list[tuple[str, dict[str, Any]]],
    ) -> int:
        """Insert a batch of L1 quote events into the quotes_l1 table."""
        rows: list[dict[str, Any]] = []

        for _msg_id, payload in batch:
            try:
                event = QuoteL1Event.model_validate(payload)
            except Exception as e:
                log.warning(
                    "persistence.invalid_quote_payload",
                    error=str(e),
                )
                continue

            instrument_id = self._instrument_cache.get(event.canonical_symbol)
            if instrument_id is None:
                continue

            rows.append(
                {
                    "instrument_id": instrument_id,
                    "ts": event.ts,
                    "bid": event.bid,
                    "bid_size": event.bid_size,
                    "ask": event.ask,
                    "ask_size": event.ask_size,
                }
            )

        if not rows:
            return 0

        async with session_scope() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO quotes_l1
                        (instrument_id, ts, bid, bid_size, ask, ask_size)
                    VALUES
                        (:instrument_id, :ts, :bid, :bid_size, :ask, :ask_size)
                    ON CONFLICT (instrument_id, ts) DO NOTHING
                    """
                ),
                rows,
            )

        self._quotes_written_1m += len(rows)
        return len(rows)

    async def _heartbeat(self) -> None:
        """Log per-minute write statistics."""
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                log.info(
                    "persistence.heartbeat",
                    trades_written_1m=self._trades_written_1m,
                    quotes_written_1m=self._quotes_written_1m,
                    errors_1m=self._errors_1m,
                    ts=datetime.utcnow().isoformat() + "Z",
                )
                self._trades_written_1m = 0
                self._quotes_written_1m = 0
                self._errors_1m = 0
        except asyncio.CancelledError:
            raise

    def shutdown(self) -> None:
        self._shutdown.set()


# ============================================================
# Entrypoint
# ============================================================


async def amain() -> None:
    _configure_logging()
    worker = PersistenceWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.shutdown)

    try:
        await worker.run()
    except Exception as e:
        log.exception("persistence.fatal", error=str(e))
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(amain())
