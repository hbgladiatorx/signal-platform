"""Polygon aggregates → historical backfill.

Pulls 1-minute aggregate bars from Polygon's ``/v2/aggs`` endpoint and feeds them
into the SAME synthetic-trade → continuous-aggregate machinery used for crypto
backfill (``packages.backtest.historical_backfill``), so backtests can read
Polygon-sourced equity/option bars from ``cagg_bars_*`` exactly like crypto.

Works for equities (``MSFT@ALPACA``) and single-leg options (the OCC canonical
``AAPL250117C00150000@ALPACA``); the Polygon ticker is read from
``instruments.metadata.polygon_ticker`` (options use the ``O:`` prefix).

Run:
    python -m packages.backtest.sources.polygon_aggs \
        --symbol MSFT@ALPACA --start 2026-05-01 --end 2026-05-15
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.backtest.historical_backfill import (
    DB_INSERT_BATCH,
    bulk_insert_trades,
    earliest_real_trade,
    refresh_caggs,
    synth_trades_from_kline,
)

AGGS_URL = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}"
MAX_BARS_PER_CALL = 50000
HTTP_TIMEOUT_S = 30
MAX_RETRIES = 5


def _build_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        raise RuntimeError("POLYGON_API_KEY is not set")
    return key


async def lookup_polygon_instrument(engine, canonical_symbol: str) -> tuple[int, str]:
    """Return (instrument_id, polygon_ticker). Uses metadata.polygon_ticker when
    present, else the native symbol."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, native_symbol, metadata FROM instruments "
                "WHERE canonical_symbol = :c"
            ),
            {"c": canonical_symbol},
        )
        row = result.first()
    if row is None:
        raise ValueError(f"No instrument with canonical_symbol={canonical_symbol!r}")
    meta = row[2] or {}
    ticker = meta.get("polygon_ticker") or row[1]
    return int(row[0]), str(ticker)


async def fetch_aggs(
    http: aiohttp.ClientSession, ticker: str, start_ms: int, end_ms: int, api_key: str
) -> list[dict]:
    """Fetch 1-minute aggregates for a window (paginates via next_url)."""
    url: str | None = AGGS_URL.format(ticker=ticker, start=start_ms, end=end_ms)
    params: dict[str, str] = {
        "adjusted": "true",
        "sort": "asc",
        "limit": str(MAX_BARS_PER_CALL),
        "apiKey": api_key,
    }
    out: list[dict] = []
    while url:
        for attempt in range(MAX_RETRIES):
            try:
                async with http.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2**attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == MAX_RETRIES - 1:
                    raise RuntimeError(f"Polygon aggs fetch failed: {e}") from e
                await asyncio.sleep(2**attempt)
        out.extend(data.get("results", []) or [])
        next_url = data.get("next_url")
        if not next_url:
            break
        url = next_url
        params = {"apiKey": api_key}
    return out


def _agg_to_kline(agg: dict) -> list[Any]:
    """Map a Polygon agg {t,o,h,l,c,v} to the Binance kline list shape
    [open_ms, open, high, low, close, volume] that synth_trades_from_kline wants."""
    return [int(agg["t"]), agg["o"], agg["h"], agg["l"], agg["c"], agg.get("v", 0)]


async def main_async(args: argparse.Namespace) -> int:
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError(f"--end ({args.end}) must be after --start ({args.start})")

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    api_key = _api_key()
    try:
        instrument_id, ticker = await lookup_polygon_instrument(engine, args.symbol)
        print(f"Resolved: instrument_id={instrument_id} polygon_ticker={ticker}")

        # Overlap safety: don't backfill into the window of real ingested trades.
        earliest_real = await earliest_real_trade(engine, instrument_id)
        if earliest_real is not None and earliest_real <= start:
            print(
                f"ERROR: range [{start}, {end}] overlaps real trades "
                f"(earliest {earliest_real}). Refusing.",
                file=sys.stderr,
            )
            return 1
        if earliest_real is not None and earliest_real < end:
            end = earliest_real.replace(second=0, microsecond=0) - timedelta(minutes=1)
            print(f"Capping --end to {end.isoformat()} to avoid overlap.")
            if end <= start:
                print("Nothing to backfill after cap.", file=sys.stderr)
                return 1

        wall = time.monotonic()
        total_bars = 0
        accumulator: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as http:
            # Window the range so each call stays within the bar cap.
            window = timedelta(minutes=MAX_BARS_PER_CALL)
            cur = start
            while cur < end:
                w_end = min(cur + window, end)
                aggs = await fetch_aggs(
                    http,
                    ticker,
                    int(cur.timestamp() * 1000),
                    int(w_end.timestamp() * 1000),
                    api_key,
                )
                for agg in aggs:
                    trades = synth_trades_from_kline(instrument_id, _agg_to_kline(agg))
                    if trades:
                        accumulator.extend(trades)
                        total_bars += 1
                    if len(accumulator) >= DB_INSERT_BATCH:
                        await bulk_insert_trades(engine, accumulator)
                        accumulator = []
                print(f"  fetched {cur.date()} → {w_end.date()}: {len(aggs)} bars")
                cur = w_end
            if accumulator:
                await bulk_insert_trades(engine, accumulator)

        print(f"\nInserted synthetic trades for {total_bars:,} 1m bars.")
        if total_bars:
            await refresh_caggs(engine, start, end)
        print(f"DONE in {time.monotonic() - wall:.1f}s")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Polygon 1m aggregates")
    parser.add_argument("--symbol", required=True, help="canonical symbol, e.g. MSFT@ALPACA")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
