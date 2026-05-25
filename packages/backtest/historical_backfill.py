"""Historical backfill — CORRECTED.

Pulls historical 1-minute OHLCV bars from Binance.US klines REST API and
writes them as synthetic trades into the `trades` table, then refreshes
the continuous aggregate chain so the data is visible to backtests.

THE PRIOR VERSION OF THIS SCRIPT WAS WRONG.
  Earlier code wrote rows directly into the `bars` table at the requested
  resolution. But backtests query `cagg_bars_*` views which aggregate FROM
  `trades`, NOT from `bars`. The bars table is a separate denormalized
  cache used elsewhere; writing into it produced dead data.

WHY SYNTHETIC TRADES:
  The cagg's aggregation semantics are:
      first(price, ts)     AS open
      last(price, ts)      AS close
      max(price)           AS high
      min(price)           AS low
      sum(quantity)        AS volume
      count(*)             AS trade_count
      sum(price*quantity)  AS price_volume_sum   (used for VWAP)

  Given a Binance.US kline (open, high, low, close, volume), we can
  reconstruct the cagg's output exactly for OHLC and volume by inserting
  four synthetic trades in a specific time order:

      t=00s   price=open    quantity=volume/4   (first → cagg open)
      t=20s   price=high    quantity=volume/4   (max  → cagg high)
      t=40s   price=low     quantity=volume/4   (min  → cagg low)
      t=59s   price=close   quantity=volume/4   (last → cagg close)

  This works because for any valid kline: high >= max(open, close, low)
  and low <= min(open, close, high), so max/min pick the right values.

  trade_count comes out to 4 per bar (vs the real Binance count). VWAP
  becomes (open+high+low+close)/4 — the "typical price" approximation,
  within a few bps of true VWAP. Acceptable for backtest research.

USAGE:
  docker exec -it signal_api python -m packages.backtest.historical_backfill \\
      --symbol BTC-USDT@BINANCEUS \\
      --start 2024-01-01 \\
      --end 2025-01-01

  Always backfills at 1-minute granularity (the source of the cagg chain).
  Higher resolutions (5m, 15m, 1h, 4h, 1d) are produced by refreshing the
  cagg chain at the end of this script. No need to invoke per-resolution.

SAFETY:
  - The script REFUSES to insert trades for any time range that overlaps
    existing trades (avoids double-counting against real-time ingestion).
  - venue_trade_id is deterministic: "backfill-{kline_ms}-{idx}". This
    makes inserts idempotent under ON CONFLICT DO NOTHING.
  - Cagg refresh is scoped to [start, end] only — does not disturb
    existing materializations outside this window.
"""
from __future__ import annotations

import argparse
import asyncio
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
MAX_LIMIT_PER_CALL = 1000        # bars per Binance call (max allowed)
SELF_RATE_LIMIT_CALLS_PER_MIN = 400
MAX_RETRIES_PER_CALL = 5
HTTP_TIMEOUT_S = 30
DB_INSERT_BATCH = 5000           # trades per INSERT — 4 trades × 1250 klines

# The cagg refresh chain, in dependency order.
CAGG_REFRESH_ORDER = [
    "cagg_bars_1m",   # reads from trades
    "cagg_bars_5m",   # reads from cagg_bars_1m
    "cagg_bars_15m",
    "cagg_bars_1h",
    "cagg_bars_4h",
    "cagg_bars_1d",
]


# ============================================================
# Binance.US fetch
# ============================================================
async def fetch_klines(
    session: aiohttp.ClientSession,
    native_symbol: str,
    start_ms: int,
    end_ms: int,
    limit: int = MAX_LIMIT_PER_CALL,
) -> list[list[Any]]:
    """Fetch one batch of 1m klines from Binance.US."""
    params = {
        "symbol": native_symbol,
        "interval": "1m",
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
        f"Failed to fetch klines after {MAX_RETRIES_PER_CALL} retries; last={last_err}"
    )


# ============================================================
# Kline → 4 synthetic trades
# ============================================================
# Seconds-within-minute for each of the 4 synthetic trades.
# Order matters: open first, close last (cagg uses first/last by ts).
# High and low in middle, in either order (max/min don't care).
_SYNTH_OFFSETS = (0, 20, 40, 59)


def synth_trades_from_kline(
    instrument_id: int,
    kline: list[Any],
) -> list[dict[str, Any]] | None:
    """Convert one Binance.US 1m kline into 4 synthetic trades.

    Returns None if the kline has zero volume (no trade activity to model).
    """
    open_ms = int(kline[0])
    open_p = Decimal(str(kline[1]))
    high_p = Decimal(str(kline[2]))
    low_p = Decimal(str(kline[3]))
    close_p = Decimal(str(kline[4]))
    volume = Decimal(str(kline[5]))

    if volume <= 0:
        # Zero-volume bar: skip. Either the asset wasn't trading, or this
        # is a pre-listing window. No trades to synthesize.
        return None

    qty_each = volume / Decimal(4)
    base_ts = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)

    # Map the 4 prices in cagg-correct order:
    # [0] open  → t=0s  → first(price, ts) picks this
    # [1] high  → t=20s → max picks this
    # [2] low   → t=40s → min picks this
    # [3] close → t=59s → last(price, ts) picks this
    prices = (open_p, high_p, low_p, close_p)

    trades = []
    for idx, (offset_s, price) in enumerate(zip(_SYNTH_OFFSETS, prices)):
        trades.append({
            "instrument_id": instrument_id,
            "ts": base_ts + timedelta(seconds=offset_s),
            "price": price,
            "quantity": qty_each,
            "side": None,  # historical, side unknown
            "venue_trade_id": f"backfill-{open_ms}-{idx}",
        })
    return trades


# ============================================================
# DB
# ============================================================

def _build_db_url() -> str:
    """Build an async DATABASE_URL from env vars."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
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
                f"No instrument with canonical_symbol={canonical_symbol!r}"
            )
        if str(row[2]).upper() != "BINANCEUS":
            raise ValueError(
                f"Instrument is venue={row[2]}, not BINANCEUS"
            )
        return int(row[0]), str(row[1])


async def earliest_real_trade(engine, instrument_id: int) -> datetime | None:
    """Return the earliest ts in trades for this instrument, or None if no rows."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT MIN(ts) FROM trades WHERE instrument_id = :iid"),
            {"iid": instrument_id},
        )
        return result.scalar()


_INSERT_TRADES_SQL = text(
    """
    INSERT INTO trades (instrument_id, ts, price, quantity, side, venue_trade_id)
    VALUES (:instrument_id, :ts, :price, :quantity, :side, :venue_trade_id)
    ON CONFLICT (instrument_id, ts, venue_trade_id) DO NOTHING
    """
)


async def bulk_insert_trades(engine, batch: list[dict[str, Any]]) -> int:
    """Bulk insert one batch of trades.

    Returns batch size (rows attempted). asyncpg executemany returns
    rowcount=-1, so we can't reliably distinguish actual inserts from
    ON CONFLICT skips. The verification via cagg_bars_1d count is
    the source of truth.
    """
    if not batch:
        return 0
    async with engine.begin() as conn:
        await conn.execute(_INSERT_TRADES_SQL, batch)
    return len(batch)


async def refresh_caggs(
    engine,
    start: datetime,
    end: datetime,
) -> None:
    """Refresh the cagg chain for the backfilled window, in dependency order."""
    print()
    print("Refreshing continuous aggregates (this may take a few minutes):")
    # CALL refresh_continuous_aggregate must run outside a transaction.
    # SQLAlchemy's AUTOCOMMIT isolation level achieves this.
    from sqlalchemy.ext.asyncio import create_async_engine as _engine_factory
    # We use the existing engine but with autocommit
    for cagg_name in CAGG_REFRESH_ORDER:
        t0 = time.monotonic()
        print(f"  [{cagg_name}] refreshing {start.date()} → {end.date()} ...", end=" ", flush=True)
        # Inline as TIMESTAMPTZ literals — asyncpg cannot infer types for the
        # overloaded refresh_continuous_aggregate CALL via prepared statement.
        start_lit = "TIMESTAMPTZ '" + start.isoformat() + "'"
        end_lit = "TIMESTAMPTZ '" + end.isoformat() + "'"
        sql_str = f"CALL refresh_continuous_aggregate('{cagg_name}', {start_lit}, {end_lit})"
        async with engine.connect() as conn:
            conn_with_autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn_with_autocommit.execute(text(sql_str))
        elapsed = time.monotonic() - t0
        print(f"done in {elapsed:.1f}s")


# ============================================================
# Main
# ============================================================
async def main_async(args: argparse.Namespace) -> int:
    # Parse date range
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError(f"--end ({args.end}) must be after --start ({args.start})")

    res_seconds = 60  # 1m bars
    chunk_seconds = MAX_LIMIT_PER_CALL * res_seconds

    total_seconds = (end - start).total_seconds()
    estimated_klines = int(total_seconds / res_seconds)
    estimated_trades = estimated_klines * 4
    estimated_calls = (estimated_klines // MAX_LIMIT_PER_CALL) + 1
    min_call_interval_s = 60.0 / SELF_RATE_LIMIT_CALLS_PER_MIN
    estimated_runtime_s = estimated_calls * min_call_interval_s

    print(f"Backfill plan:")
    print(f"  Symbol:             {args.symbol}")
    print(f"  Range:              {start.isoformat()} → {end.isoformat()}")
    print(f"  Granularity:        1m (4 synthetic trades per kline)")
    print(f"  Estimated klines:   {estimated_klines:,}")
    print(f"  Estimated trades:   {estimated_trades:,}")
    print(f"  Estimated calls:    {estimated_calls:,}")
    print(f"  Estimated runtime:  ~{estimated_runtime_s:.0f}s ({estimated_runtime_s / 60:.1f} min)")
    print(f"                      (+ cagg refresh time)")
    print()

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)

    try:
        instrument_id, native_symbol = await lookup_instrument(engine, args.symbol)
        print(f"Resolved: instrument_id={instrument_id} native_symbol={native_symbol}")

        # Safety: cap end at the start of real trade data
        earliest_real = await earliest_real_trade(engine, instrument_id)
        if earliest_real is not None:
            print(f"Earliest existing trade for this instrument: {earliest_real.isoformat()}")
            if earliest_real <= start:
                print(
                    f"ERROR: backfill range [{start}, {end}] entirely overlaps real "
                    f"trades (earliest {earliest_real}). Refusing to insert."
                )
                return 1
            if earliest_real < end:
                # Cap end to one minute before real data starts
                safe_end = earliest_real.replace(second=0, microsecond=0) - timedelta(minutes=1)
                print(
                    f"Capping --end from {end.isoformat()} to {safe_end.isoformat()} "
                    f"to avoid overlap with real trades."
                )
                end = safe_end
                if end <= start:
                    print("ERROR: nothing to backfill after applying safety cap.")
                    return 1
        print()

        # Main loop
        wall_start = time.monotonic()
        last_call_at = 0.0
        total_klines = 0
        total_trades_synthesized = 0
        total_trades_inserted = 0
        accumulator: list[dict[str, Any]] = []

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

                raw = await fetch_klines(session, native_symbol, start_ms, end_ms)
                if not raw:
                    print(f"  [empty] {current_start.date()} — advancing")
                    current_start = chunk_end
                    continue

                # Convert klines → synthetic trades
                for kline in raw:
                    synth = synth_trades_from_kline(instrument_id, kline)
                    if synth is not None:
                        accumulator.extend(synth)
                        total_trades_synthesized += len(synth)
                    total_klines += 1

                # Flush accumulator in batches
                while len(accumulator) >= DB_INSERT_BATCH:
                    batch = accumulator[:DB_INSERT_BATCH]
                    accumulator = accumulator[DB_INSERT_BATCH:]
                    inserted = await bulk_insert_trades(engine, batch)
                    total_trades_inserted += inserted

                # Advance
                last_ts = datetime.fromtimestamp(int(raw[-1][0]) / 1000, tz=timezone.utc)
                next_start = last_ts + timedelta(seconds=res_seconds)
                if next_start <= current_start:
                    next_start = chunk_end
                current_start = next_start

                pct = min(100.0, 100.0 * total_klines / max(1, estimated_klines))
                elapsed = time.monotonic() - wall_start
                print(
                    f"  [{pct:5.1f}%] klines={total_klines:,} "
                    f"synth={total_trades_synthesized:,} "
                    f"inserted={total_trades_inserted:,} "
                    f"→ {last_ts.isoformat()} (elapsed {elapsed:.1f}s)"
                )

        # Flush remainder
        if accumulator:
            inserted = await bulk_insert_trades(engine, accumulator)
            total_trades_inserted += inserted

        fetch_elapsed = time.monotonic() - wall_start
        print()
        print(f"Fetch + insert: {fetch_elapsed:.1f}s")
        print(f"  Klines fetched:      {total_klines:,}")
        print(f"  Trades synthesized:  {total_trades_synthesized:,}")
        print(f"  Trades inserted:     {total_trades_inserted:,}")
        skipped = total_trades_synthesized - total_trades_inserted
        if skipped > 0:
            print(f"  Skipped duplicates:  {skipped:,}")

        if total_trades_inserted == 0:
            print()
            print("No new trades inserted — skipping cagg refresh.")
            return 0

        # Refresh caggs
        await refresh_caggs(engine, start, end)

        # Verify
        print()
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT count(*), min(bucket)::date, max(bucket)::date "
                    "FROM cagg_bars_1d WHERE instrument_id = :iid "
                    "AND bucket >= :start AND bucket < :end"
                ),
                {"iid": instrument_id, "start": start, "end": end},
            )
            row = res.first()
            n, mn, mx = row[0], row[1], row[2]
            print(f"VERIFY cagg_bars_1d in range: {n} buckets, {mn} → {mx}")

        print()
        print("=" * 60)
        print(f"DONE. Total wall time: {time.monotonic() - wall_start:.1f}s")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical bars as synthetic trades.",
    )
    parser.add_argument("--symbol", required=True,
                        help="Canonical symbol e.g. 'BTC-USDT@BINANCEUS'")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")
    args = parser.parse_args()
    rc = asyncio.run(main_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
