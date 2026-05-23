"""Live bar-builder service.

Consumes trade events from STREAM_TRADES_RAW via consumer group
'bar-builder'. Maintains in-memory current-bar state for each
(canonical_symbol, resolution) pair across all six resolutions:
1m, 5m, 15m, 1h, 4h, 1d.

On each trade:
  - For each resolution:
    - Compute the bucket start time (Unix seconds, floor-aligned to interval)
    - If the trade falls into a new bucket: close the previous bar by
      publishing to STREAM_BARS_CLOSED, open a fresh bar with the trade as O=H=L=C
    - If same bucket: update H = max(H, price), L = min(L, price),
      C = price, V += quantity, trade_count += 1, price_volume_sum += price * quantity
  - Throttled: publish in-progress bar snapshot to STREAM_BARS_LIVE at most
    once per second per (symbol, resolution).

Trade events on trades:raw carry `canonical_symbol`, not `instrument_id`
(the persistence_worker resolves the FK at DB-write time). Bar events
follow the same convention: downstream consumers (backtest, paper-trade)
resolve canonical_symbol → instrument_id on their own as needed.

In-memory only. Restart-safe via Redis Streams consumer-group semantics:
on restart we resume from the last-acked id.

VWAP correctness: we carry price_volume_sum and volume separately. The
true VWAP at any moment is price_volume_sum / volume. Phase 2's analytics
package can compute period-VWAP correctly by aggregating these components.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from packages.data.messagebus import (
    GROUP_BAR_BUILDER,
    RedisStreamsBus,
    STREAM_BARS_CLOSED,
    STREAM_BARS_LIVE,
    STREAM_TRADES_RAW,
)


# ============================================================
# Logging
# ============================================================
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


# ============================================================
# Constants
# ============================================================
RESOLUTIONS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

CONSUMER_NAME = os.environ.get("HOSTNAME", "bar-builder-1")
BATCH_SIZE = 100
BLOCK_MS = 5_000
LIVE_PUBLISH_INTERVAL_S = 1.0


# ============================================================
# In-memory state
# ============================================================
@dataclass
class BarState:
    """In-progress bar state for a (canonical_symbol, resolution) pair."""

    canonical_symbol: str
    resolution: str
    bucket_start_ts: int  # Unix seconds, floor-aligned to resolution
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    price_volume_sum: Decimal
    last_published_monotonic: float  # Last bars:live publish time


# (canonical_symbol, resolution) -> BarState
_bars: dict[tuple[str, str], BarState] = {}


# ============================================================
# Helpers
# ============================================================
def _bucket_start(unix_seconds: int, resolution: str) -> int:
    interval = RESOLUTION_SECONDS[resolution]
    return (unix_seconds // interval) * interval


def _vwap(state: BarState) -> Decimal | None:
    if state.volume <= 0:
        return None
    return state.price_volume_sum / state.volume


def _state_to_payload(state: BarState, *, closed: bool) -> dict[str, Any]:
    vwap = _vwap(state)
    return {
        "canonical_symbol": state.canonical_symbol,
        "resolution": state.resolution,
        "bucket_start": state.bucket_start_ts,
        "open": str(state.open),
        "high": str(state.high),
        "low": str(state.low),
        "close": str(state.close),
        "volume": str(state.volume),
        "trade_count": state.trade_count,
        "vwap": str(vwap) if vwap is not None else None,
        "closed": closed,
    }


def _parse_ts(ts: Any) -> int:
    """Parse a timestamp to Unix seconds. Accepts numeric (s or ms) and ISO strings."""
    if isinstance(ts, (int, float)):
        # If too large, assume milliseconds
        return int(ts) if ts < 10_000_000_000 else int(ts // 1000)
    if isinstance(ts, str):
        clean = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(clean)
        return int(dt.timestamp())
    raise ValueError(f"Unparseable timestamp: {ts!r}")


def _parse_decimal(v: Any) -> Decimal:
    return Decimal(str(v))


# ============================================================
# Trade processing
# ============================================================
async def process_trade(bus: RedisStreamsBus, trade: dict[str, Any]) -> None:
    """Update all six in-progress bars for the instrument with this trade."""
    canonical_symbol = trade.get("canonical_symbol")
    if not canonical_symbol:
        log.warning(
            "bar_builder.trade.missing_canonical_symbol",
            trade_keys=list(trade.keys()),
        )
        return

    try:
        price = _parse_decimal(trade["price"])
        quantity = _parse_decimal(trade["quantity"])
        ts_sec = _parse_ts(trade["ts"])
    except (KeyError, ValueError) as e:
        log.warning("bar_builder.trade.parse_error", err=str(e), symbol=canonical_symbol)
        return

    now_mono = time.monotonic()

    for resolution in RESOLUTIONS:
        bucket = _bucket_start(ts_sec, resolution)
        key = (canonical_symbol, resolution)
        state = _bars.get(key)

        if state is None or state.bucket_start_ts != bucket:
            # Close the previous bar (only on a genuine forward transition).
            if state is not None and state.bucket_start_ts < bucket:
                await bus.publish(
                    STREAM_BARS_CLOSED, _state_to_payload(state, closed=True)
                )
                log.info(
                    "bar_builder.bar_closed",
                    symbol=state.canonical_symbol,
                    resolution=state.resolution,
                    bucket_start=state.bucket_start_ts,
                    trade_count=state.trade_count,
                    volume=str(state.volume),
                )

            # Open new bar — trade defines O=H=L=C
            state = BarState(
                canonical_symbol=canonical_symbol,
                resolution=resolution,
                bucket_start_ts=bucket,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=quantity,
                trade_count=1,
                price_volume_sum=price * quantity,
                last_published_monotonic=0.0,
            )
            _bars[key] = state
        else:
            if price > state.high:
                state.high = price
            if price < state.low:
                state.low = price
            state.close = price
            state.volume += quantity
            state.trade_count += 1
            state.price_volume_sum += price * quantity

        # Throttled live publish
        if now_mono - state.last_published_monotonic >= LIVE_PUBLISH_INTERVAL_S:
            await bus.publish(STREAM_BARS_LIVE, _state_to_payload(state, closed=False))
            state.last_published_monotonic = now_mono


# ============================================================
# Main loop
# ============================================================
async def main_loop() -> None:
    bus = RedisStreamsBus()
    await bus.ensure_group(STREAM_TRADES_RAW, GROUP_BAR_BUILDER)
    log.info(
        "bar_builder.starting",
        stream=STREAM_TRADES_RAW,
        group=GROUP_BAR_BUILDER,
        consumer=CONSUMER_NAME,
        resolutions=list(RESOLUTIONS),
    )

    shutdown_event = asyncio.Event()

    def _on_signal(sig: int) -> None:
        log.info("bar_builder.signal", sig=sig)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            pass

    while not shutdown_event.is_set():
        try:
            messages = await bus.consume(
                stream=STREAM_TRADES_RAW,
                group=GROUP_BAR_BUILDER,
                consumer=CONSUMER_NAME,
                count=BATCH_SIZE,
                block_ms=BLOCK_MS,
            )
        except Exception as e:
            log.error("bar_builder.consume_error", err=str(e))
            await asyncio.sleep(1.0)
            continue

        if not messages:
            continue

        ack_ids: list[str] = []
        for msg_id, payload in messages:
            try:
                await process_trade(bus, payload)
            except Exception as e:
                log.error("bar_builder.process_error", err=str(e), msg_id=msg_id)
            # Always ack: a poison-pill message should not block the stream.
            ack_ids.append(msg_id)

        try:
            await bus.ack(STREAM_TRADES_RAW, GROUP_BAR_BUILDER, ack_ids)
        except Exception as e:
            log.error("bar_builder.ack_error", err=str(e))

    log.info("bar_builder.stopping")
    await bus.close()
    log.info("bar_builder.stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        sys.exit(0)
