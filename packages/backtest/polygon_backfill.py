"""Historical backfill from Polygon.io aggregates.

Mirrors ``historical_backfill`` (Binance.US) but sources 1-minute bars from
Polygon's aggregates API. Each Polygon bar becomes four synthetic trades in
the ``trades`` table — exactly the representation the continuous-aggregate
chain expects — so Polygon equities become backtestable on the same footing as
Binance crypto.

USAGE:
  docker exec -it signal_api python -m packages.backtest.polygon_backfill \\
      --symbol AAPL-USD@POLYGON \\
      --start 2024-01-01 \\
      --end 2025-01-01

Reuses the synthetic-trade conversion, bulk insert, and cagg-refresh helpers
from ``historical_backfill`` so the two backfills stay byte-for-byte consistent
in how they populate the bar chain.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.adapters.equity.polygon import PolygonClient, to_native
from packages.backtest.historical_backfill import (
    _build_db_url,
    bulk_insert_trades,
    earliest_real_trade,
    refresh_caggs,
    synth_trades_from_kline,
)

DB_INSERT_BATCH = 5000


async def lookup_polygon_instrument(engine, canonical_symbol: str) -> tuple[int, str]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, native_symbol, venue FROM instruments "
                    "WHERE canonical_symbol = :canonical"
                ),
                {"canonical": canonical_symbol},
            )
        ).first()
        if row is None:
            raise ValueError(f"No instrument with canonical_symbol={canonical_symbol!r}")
        if str(row[2]).upper() != "POLYGON":
            raise ValueError(f"Instrument is venue={row[2]}, not POLYGON")
        return int(row[0]), str(row[1])


def _agg_to_kline(result: dict[str, Any]) -> list[Any]:
    """Convert a Polygon aggregate bar into the kline list shape used by
    ``synth_trades_from_kline``: [open_ms, open, high, low, close, volume].
    """
    return [
        int(result["t"]),
        result["o"],
        result["h"],
        result["l"],
        result["c"],
        result.get("v", 0),
    ]


def _month_chunks(start: datetime, end: datetime):
    """Yield (chunk_start, chunk_end) ~monthly windows to bound result size."""
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=28), end)
        yield cur, nxt
        cur = nxt


async def main_async(args: argparse.Namespace) -> int:
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError(f"--end ({args.end}) must be after --start ({args.start})")

    ticker = to_native(args.symbol)
    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    client = PolygonClient()

    try:
        instrument_id, native_symbol = await lookup_polygon_instrument(engine, args.symbol)
        print(f"Resolved: instrument_id={instrument_id} ticker={native_symbol}")

        earliest_real = await earliest_real_trade(engine, instrument_id)
        if earliest_real is not None and earliest_real <= start:
            print(
                f"ERROR: backfill range entirely overlaps real trades "
                f"(earliest {earliest_real}). Refusing to insert."
            )
            return 1
        if earliest_real is not None and earliest_real < end:
            end = earliest_real.replace(second=0, microsecond=0) - timedelta(minutes=1)
            print(f"Capping --end to {end.isoformat()} to avoid overlap.")
            if end <= start:
                print("ERROR: nothing to backfill after applying safety cap.")
                return 1

        total_klines = 0
        total_inserted = 0
        accumulator: list[dict[str, Any]] = []

        for chunk_start, chunk_end in _month_chunks(start, end):
            results = await client.aggregates(
                ticker,
                resolution="1m",
                start=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
            )
            for r in results:
                synth = synth_trades_from_kline(instrument_id, _agg_to_kline(r))
                if synth is not None:
                    accumulator.extend(synth)
                total_klines += 1
            while len(accumulator) >= DB_INSERT_BATCH:
                batch = accumulator[:DB_INSERT_BATCH]
                accumulator = accumulator[DB_INSERT_BATCH:]
                total_inserted += await bulk_insert_trades(engine, batch)
            print(
                f"  [{chunk_start.date()} → {chunk_end.date()}] "
                f"bars={total_klines:,} inserted={total_inserted:,}"
            )

        if accumulator:
            total_inserted += await bulk_insert_trades(engine, accumulator)

        print(f"\nBars fetched: {total_klines:,}  trades inserted: {total_inserted:,}")
        if total_inserted == 0:
            print("No new trades inserted — skipping cagg refresh.")
            return 0

        await refresh_caggs(engine, start, end)
        print("\nDONE.")
        return 0
    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Polygon history as synthetic trades.")
    parser.add_argument("--symbol", required=True, help="Canonical, e.g. 'AAPL-USD@POLYGON'")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
