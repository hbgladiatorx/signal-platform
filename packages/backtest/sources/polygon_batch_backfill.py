"""Batch backfill many equity tickers from Polygon in one pass.

Why this exists: running ``polygon_aggs`` once per ticker re-runs the full
``refresh_caggs`` (a multi-resolution, whole-window continuous-aggregate
refresh) for every ticker — 50 tickers => 50 redundant full-window refreshes,
which is brutal on a small box. This tool instead:

  1. Seeds the instruments rows (idempotent INSERT ... ON CONFLICT).
  2. Fetches Polygon 1m aggs -> synthetic trades -> bulk insert, for every
     ticker, SKIPPING any ticker that already has trades covering the window
     (so it's resumable).
  3. Refreshes the cagg chain ONCE at the end, in quarterly chunks (bounded
     memory) over the union window.

Run:
    python -m packages.backtest.sources.polygon_batch_backfill \
        --tickers AAPL,MSFT,GOOGL,... --start 2023-01-01 --end 2025-01-01
    # or
    python -m packages.backtest.sources.polygon_batch_backfill \
        --tickers-file /path/tickers.txt --start 2023-01-01 --end 2025-01-01
"""
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.backtest.historical_backfill import (
    DB_INSERT_BATCH,
    CAGG_REFRESH_ORDER,
    bulk_insert_trades,
    synth_trades_from_kline,
)
from packages.backtest.sources.polygon_aggs import (
    MAX_BARS_PER_CALL,
    _agg_to_kline,
    _api_key,
    _build_db_url,
    fetch_aggs,
)

VENUE = "ALPACA"
# A ticker is considered "already backfilled" for the window if it has at least
# this many trades in [start, end). One 1m bar => ~4 synth trades, and even a
# few months of a liquid name is >> this, so the threshold cleanly separates
# "nothing there" from "already done".
SKIP_IF_TRADES_OVER = 1000


async def ensure_instrument(engine, ticker: str) -> int:
    """Idempotently ensure an equity instrument row; return its id."""
    canonical = f"{ticker}@{VENUE}"
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO instruments
                        (asset_class, canonical_symbol, venue, native_symbol,
                         metadata, active, multiplier)
                    VALUES ('equity', :c, :v, :n, '{}'::jsonb, true, 1)
                    ON CONFLICT (canonical_symbol) DO UPDATE SET active = true
                    RETURNING id
                    """
                ),
                {"c": canonical, "v": VENUE, "n": ticker},
            )
        ).first()
    return int(row[0])


async def trades_in_window(engine, instrument_id: int, start, end) -> int:
    async with engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM trades "
                    "WHERE instrument_id = :iid AND ts >= :s AND ts < :e"
                ),
                {"iid": instrument_id, "s": start, "e": end},
            )
        ).scalar_one()
    return int(n)


async def backfill_ticker(engine, http, ticker, start, end, api_key) -> int:
    """Fetch + insert synthetic trades for one ticker. Returns #1m bars."""
    instrument_id = await ensure_instrument(engine, ticker)
    existing = await trades_in_window(engine, instrument_id, start, end)
    if existing > SKIP_IF_TRADES_OVER:
        print(f"[{ticker}] already has {existing:,} trades in window — skip")
        return 0

    total_bars = 0
    accumulator: list[dict] = []
    window = timedelta(minutes=MAX_BARS_PER_CALL)
    cur = start
    while cur < end:
        w_end = min(cur + window, end)
        aggs = await fetch_aggs(
            http, ticker, int(cur.timestamp() * 1000), int(w_end.timestamp() * 1000), api_key
        )
        for agg in aggs:
            trades = synth_trades_from_kline(instrument_id, _agg_to_kline(agg))
            if trades:
                accumulator.extend(trades)
                total_bars += 1
            if len(accumulator) >= DB_INSERT_BATCH:
                await bulk_insert_trades(engine, accumulator)
                accumulator = []
        cur = w_end
    if accumulator:
        await bulk_insert_trades(engine, accumulator)
    print(f"[{ticker}] inserted synthetic trades for {total_bars:,} 1m bars")
    return total_bars


def _quarter_edges(start: datetime, end: datetime):
    """Yield (chunk_start, chunk_end) ~quarterly to bound refresh memory."""
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=92), end)
        yield cur, nxt
        cur = nxt


async def refresh_caggs_chunked(engine, start: datetime, end: datetime) -> None:
    """Refresh the cagg chain in dependency order, quarterly chunks per cagg."""
    print("\nRefreshing continuous aggregates in quarterly chunks:")
    for cagg_name in CAGG_REFRESH_ORDER:
        t0 = time.monotonic()
        for c_start, c_end in _quarter_edges(start, end):
            start_lit = "TIMESTAMPTZ '" + c_start.isoformat() + "'"
            end_lit = "TIMESTAMPTZ '" + c_end.isoformat() + "'"
            sql_str = (
                f"CALL refresh_continuous_aggregate('{cagg_name}', {start_lit}, {end_lit})"
            )
            async with engine.connect() as conn:
                ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
                await ac.execute(text(sql_str))
        print(f"  [{cagg_name}] done in {time.monotonic() - t0:.1f}s")


async def main_async(args: argparse.Namespace) -> int:
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError("--end must be after --start")

    if args.tickers_file:
        with open(args.tickers_file) as f:
            tickers = [t.strip().upper() for t in f.read().replace(",", "\n").split() if t.strip()]
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    tickers = list(dict.fromkeys(tickers))  # dedupe, keep order
    print(f"Batch backfill {len(tickers)} tickers {start.date()} -> {end.date()}")

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True, pool_size=2, max_overflow=2)
    api_key = _api_key()
    wall = time.monotonic()
    any_inserted = False
    try:
        async with aiohttp.ClientSession() as http:
            for i, ticker in enumerate(tickers, 1):
                print(f"\n=== ({i}/{len(tickers)}) {ticker} ===")
                try:
                    n = await backfill_ticker(engine, http, ticker, start, end, api_key)
                    any_inserted = any_inserted or n > 0
                except Exception as e:  # noqa: BLE001 — keep going on a bad ticker
                    print(f"[{ticker}] ERROR: {e!r} — skipping")
        if any_inserted:
            await refresh_caggs_chunked(engine, start, end)
        else:
            print("\nNo new trades inserted; skipping cagg refresh.")
        print(f"\nDONE in {time.monotonic() - wall:.1f}s")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description="Batch backfill equities from Polygon")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--tickers", help="comma-separated tickers, e.g. AAPL,MSFT,GOOGL")
    g.add_argument("--tickers-file", help="file with tickers (comma/space/newline separated)")
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    raise SystemExit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
