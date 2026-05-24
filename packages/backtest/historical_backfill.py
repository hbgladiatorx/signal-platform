"""Historical backfill of OHLCV bars from Binance.US klines REST API.

Pulls historical bars and INSERTs into the existing `bars` hypertable.
Idempotent: ON CONFLICT DO NOTHING means safe to re-run, will skip
existing rows and only fetch what's missing.

Usage (run inside the api container):

    docker exec -i signal_api python -m packages.backtest.historical_backfill \\
        --symbol BTC-USDT@BINANCEUS \\
        --resolution 1m \\
        --start 2024-01-01 \\
        --end 2025-01-01

Resolutions accepted: 1m, 5m, 15m, 1h, 4h, 1d.

Rate limit:
  Binance.US allows 1200 weight/min on /klines. With limit=1000 each call
  costs 2 weight = 600 calls/min hard ceiling. We self-limit to 400/min to
  leave headroom for real-time ingestion.

Throughput at 400 calls/min × 1000 bars/call = ~400k bars/min:
  - 1 year of 1m bars (525,600 bars):   ~80s
  - 5 years of 1m bars (2,628,000 bars): ~7 min
  - 1 year of 5m bars (105,120 bars):   ~16s
  - 1 year of 1h bars (8,760 bars):     ~2s

Notes:
  - VWAP is computed as quote_volume / base_volume from Binance's response
    (which is the true VWAP within each bar).
  - Empty responses (e.g., requesting before pair listing) are handled
    gracefully — script advances and continues.
  - Pre-existing rows are skipped via ON CONFLICT — re-running gives a
    "skipped duplicates: N" line in the summary.

Limitations of this MVP:
  - One symbol per invocation (run multiple times for multiple pairs)
  - No cancellation / pause / resume (just kill and restart; idempotency
    means no harm done)
  - No cagg refresh — if you backfill 1m data and have continuous
    aggregates for 5m/15m/etc., you'll need to manually CALL
    refresh_continuous_aggregate(...) on each.
  - Writes directly to bars table; TimescaleDB rewrites the INSERT to
    the appropriate chunk via the insert_blocker trigger.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# ============================================================
# Constants
# ============================================================

BINANCE_US_KLINES_URL = "https://api.binance.us/api/v3/klines"
MAX_LIMIT_PER_CALL = 1000
SELF_RATE_LIMIT_CALLS_PER_MIN = 400
MAX_RETRIES_PER_CALL = 5
HTTP_TIMEOUT_S = 30

# Our resolution names → Binance interval strings (they happen to match)
RESOLUTION_TO_BINANCE: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

# Seconds per resolution unit (for chunking math)
RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


log = logging.getLogger("historical_backfill")


# ============================================================
# HTTP / Binance.US
# ============================================================
async def fetch_klines(
    session: aiohttp.ClientSession,
    native_symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int = MAX_LIMIT_PER_CALL,
) -> list[list[Any]]:
    """Fetch one batch of klines. Retries with exponential backoff on
    rate-limit (429) and transient server errors (5xx)."""
    params = {
        "symbol": native_symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES_PER_CALL):
        try:
            async with session.get(
                BINANCE_US_KLINES_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
            ) as resp:
                if resp.status == 429:
                    wait_s = 2 ** attempt
                    print(f"    [rate limited 429] backing off {wait_s}s", file=sys.stderr)
                    await asyncio.sleep(wait_s)
                    continue
                if resp.status >= 500:
                    wait_s = 2 ** attempt
                    print(f"    [server {resp.status}] retrying in {wait_s}s", file=sys.stderr)
                    await asyncio.sleep(wait_s)
                    continue
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = e
            wait_s = 2 ** attempt
            print(f"    [network error: {e}] retrying in {wait_s}s", file=sys.stderr)
            await asyncio.sleep(wait_s)
    raise RuntimeError(
        f"Failed to fetch klines after {MAX_RETRIES_PER_CALL} retries; last error: {last_err}"
    )


def parse_kline(row: list[Any]) -> dict[str, Any]:
    """Convert a Binance.US kline array to a dict matching the bars schema.

    Binance kline format (positions):
       0: open_time (ms)
       1: open  2: high  3: low  4: close  5: volume
       6: close_time (ms)
       7: quote_asset_volume
       8: number_of_trades
       9-10: taker buys (unused)
       11: ignore
    """
    open_ms = int(row[0])
    open_ = Decimal(str(row[1]))
    high = Decimal(str(row[2]))
    low = Decimal(str(row[3]))
    close = Decimal(str(row[4]))
    volume = Decimal(str(row[5]))
    quote_volume = Decimal(str(row[7]))
    trade_count = int(row[8]) if row[8] is not None else None

    # VWAP = quote_volume / base_volume
    vwap: Decimal | None = (quote_volume / volume) if volume > 0 else None

    return {
        "ts": datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "trade_count": trade_count,
        "vwap": vwap,
    }


# ============================================================
# DB
# ============================================================

def _build_db_url() -> str:
    """Reconstruct an async DATABASE_URL from env vars used by the platform."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        # Normalize to asyncpg driver
        if "+psycopg2" in explicit:
            return explicit.replace("+psycopg2", "+asyncpg")
        if explicit.startswith("postgresql://") and "+" not in explicit.split("://", 1)[0]:
            return explicit.replace("postgresql://", "postgresql+asyncpg://", 1)
        return explicit

    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "signal")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DB", "signal_platform")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def lookup_instrument(engine, canonical_symbol: str) -> tuple[int, str]:
    """Resolve canonical_symbol → (instrument_id, native_symbol)."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, native_symbol, venue, active "
                "FROM instruments WHERE canonical_symbol = :canonical"
            ),
            {"canonical": canonical_symbol},
        )
        row = result.first()
        if row is None:
            raise ValueError(
                f"No instrument with canonical_symbol={canonical_symbol!r}. "
                f"Check the symbol spelling or run on the right database."
            )
        instrument_id = int(row[0])
        native_symbol = str(row[1])
        venue = str(row[2])
        active = bool(row[3])
        if venue.upper() != "BINANCEUS":
            raise ValueError(
                f"Instrument {canonical_symbol} is venue={venue}, not BINANCEUS. "
                f"This script only supports Binance.US."
            )
        if not active:
            print(
                f"[warning] instrument {canonical_symbol} is marked active=false; "
                f"continuing anyway.",
                file=sys.stderr,
            )
        return instrument_id, native_symbol


async def count_existing(engine, instrument_id: int, resolution: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM bars "
                "WHERE instrument_id = :iid AND resolution = :res"
            ),
            {"iid": instrument_id, "res": resolution},
        )
        return int(result.scalar() or 0)


_INSERT_BARS_SQL = text(
    """
    INSERT INTO bars (
        instrument_id, resolution, ts,
        open, high, low, close, volume, trade_count, vwap
    )
    VALUES (
        :instrument_id, :resolution, :ts,
        :open, :high, :low, :close, :volume, :trade_count, :vwap
    )
    ON CONFLICT (instrument_id, resolution, ts) DO NOTHING
    """
)


async def insert_bars(
    engine,
    instrument_id: int,
    resolution: str,
    bars: list[dict[str, Any]],
) -> int:
    """Bulk insert. Returns the number of NEW rows (post-ON-CONFLICT)."""
    if not bars:
        return 0
    rows = [
        {
            "instrument_id": instrument_id,
            "resolution": resolution,
            "ts": bar["ts"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "trade_count": bar["trade_count"],
            "vwap": bar["vwap"],
        }
        for bar in bars
    ]
    async with engine.begin() as conn:
        before = (await conn.execute(
            text(
                "SELECT count(*) FROM bars "
                "WHERE instrument_id = :iid AND resolution = :res "
                "AND ts >= :ts_min AND ts <= :ts_max"
            ),
            {
                "iid": instrument_id,
                "res": resolution,
                "ts_min": bars[0]["ts"],
                "ts_max": bars[-1]["ts"],
            },
        )).scalar() or 0

        await conn.execute(_INSERT_BARS_SQL, rows)

        after = (await conn.execute(
            text(
                "SELECT count(*) FROM bars "
                "WHERE instrument_id = :iid AND resolution = :res "
                "AND ts >= :ts_min AND ts <= :ts_max"
            ),
            {
                "iid": instrument_id,
                "res": resolution,
                "ts_min": bars[0]["ts"],
                "ts_max": bars[-1]["ts"],
            },
        )).scalar() or 0

    return int(after - before)


# ============================================================
# Main loop
# ============================================================
async def main_async(args: argparse.Namespace) -> int:
    # Parse date range
    if args.start.lower() == "earliest":
        # Binance.US launched 2019-09; data only exists from then on
        start = datetime(2019, 9, 1, tzinfo=timezone.utc)
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError(f"--end ({args.end}) must be after --start ({args.start})")

    interval = RESOLUTION_TO_BINANCE[args.resolution]
    res_seconds = RESOLUTION_SECONDS[args.resolution]
    chunk_seconds = MAX_LIMIT_PER_CALL * res_seconds  # wall-time covered per call

    total_seconds = (end - start).total_seconds()
    estimated_bars = int(total_seconds / res_seconds)
    estimated_calls = (estimated_bars // MAX_LIMIT_PER_CALL) + 1

    # Estimated wall-clock time (assuming rate limit is the bottleneck)
    min_call_interval_s = 60.0 / SELF_RATE_LIMIT_CALLS_PER_MIN
    estimated_runtime_s = estimated_calls * min_call_interval_s

    print(f"Backfill plan:")
    print(f"  Symbol:          {args.symbol}")
    print(f"  Resolution:      {args.resolution}")
    print(f"  Range:           {start.isoformat()} → {end.isoformat()}")
    print(f"  Estimated bars:  {estimated_bars:,}")
    print(f"  Estimated calls: {estimated_calls:,}")
    print(f"  Estimated time:  ~{estimated_runtime_s:.0f}s ({estimated_runtime_s / 60:.1f} min)")
    print()

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)

    try:
        # Resolve instrument
        instrument_id, native_symbol = await lookup_instrument(engine, args.symbol)
        print(f"Resolved: instrument_id={instrument_id} native_symbol={native_symbol}")

        existing_before = await count_existing(engine, instrument_id, args.resolution)
        print(f"Existing rows for this instrument/resolution: {existing_before:,}")
        print()

        # Main fetch loop
        total_fetched = 0
        total_inserted = 0
        last_call_at = 0.0
        wall_start = time.monotonic()

        async with aiohttp.ClientSession() as session:
            current_start = start
            while current_start < end:
                chunk_end = min(current_start + timedelta(seconds=chunk_seconds), end)

                start_ms = int(current_start.timestamp() * 1000)
                end_ms = int(chunk_end.timestamp() * 1000)

                # Rate limit
                now = time.monotonic()
                wait = min_call_interval_s - (now - last_call_at)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_call_at = time.monotonic()

                raw = await fetch_klines(
                    session, native_symbol, interval, start_ms, end_ms
                )

                if not raw:
                    # No data for this window (probably before pair listing).
                    # Advance and continue.
                    current_start = chunk_end
                    print(
                        f"  [empty] {current_start.date()} — advancing"
                    )
                    continue

                bars = [parse_kline(row) for row in raw]
                inserted = await insert_bars(
                    engine, instrument_id, args.resolution, bars
                )
                total_fetched += len(bars)
                total_inserted += inserted

                # Advance: start the next window AFTER the last bar we got
                last_ts = bars[-1]["ts"]
                next_start = last_ts + timedelta(seconds=res_seconds)
                if next_start <= current_start:
                    # Defensive: shouldn't happen, but don't infinite-loop
                    next_start = chunk_end
                current_start = next_start

                pct = min(100.0, 100.0 * total_fetched / max(1, estimated_bars))
                elapsed = time.monotonic() - wall_start
                print(
                    f"  [{pct:5.1f}%] fetched={total_fetched:,} "
                    f"inserted={total_inserted:,} ({len(bars)} this call) "
                    f"→ {last_ts.isoformat()} (elapsed {elapsed:.1f}s)"
                )

        existing_after = await count_existing(engine, instrument_id, args.resolution)

        print()
        print("=" * 60)
        print(f"DONE")
        print(f"  Wall time:           {time.monotonic() - wall_start:.1f}s")
        print(f"  Bars fetched:        {total_fetched:,}")
        print(f"  New rows inserted:   {total_inserted:,}")
        print(f"  Skipped duplicates:  {total_fetched - total_inserted:,}")
        print(f"  Existing before:     {existing_before:,}")
        print(f"  Existing after:      {existing_after:,}")
        print(f"  Net new:             {existing_after - existing_before:,}")
        return 0

    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical OHLCV bars from Binance.US.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Backfill 1 year of BTC-USDT 1m bars:
    python -m packages.backtest.historical_backfill \\
        --symbol BTC-USDT@BINANCEUS --resolution 1m \\
        --start 2024-01-01 --end 2025-01-01

  Backfill 5 years of ETH-USDT 1h bars:
    python -m packages.backtest.historical_backfill \\
        --symbol ETH-USDT@BINANCEUS --resolution 1h \\
        --start 2021-01-01 --end 2026-01-01

  Backfill from listing date (no-op for pre-listing windows):
    python -m packages.backtest.historical_backfill \\
        --symbol BTC-USDT@BINANCEUS --resolution 1d \\
        --start earliest --end 2026-01-01
""",
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Canonical symbol, e.g. 'BTC-USDT@BINANCEUS'",
    )
    parser.add_argument(
        "--resolution",
        required=True,
        choices=sorted(RESOLUTION_TO_BINANCE.keys()),
        help="Bar resolution",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD (or 'earliest' for 2019-09-01)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD (exclusive)",
    )
    args = parser.parse_args()
    rc = asyncio.run(main_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
