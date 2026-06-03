"""Bulk-sync the full Binance.US spot universe into the `instruments` table.

This is the script that actually "wires in the full Binance universe" for
backtesting, paper, and live trading: it pulls every TRADING spot pair from
exchangeInfo and upserts it as an instrument row. Once present, a symbol is
usable everywhere the platform resolves instruments by canonical symbol.

Idempotent: re-running updates `native_symbol` / `base` / `quote` / status
metadata for existing rows and inserts new ones. It never deletes rows (so a
pair that delists stays in the catalog, just inactive).

USAGE:
  docker exec -it signal_api python -m packages.adapters.crypto.binance_universe_sync
  # Only USD-quoted pairs, and mark them active for ingestion:
  ... binance_universe_sync --quote USDT,USD,USDC --activate

The same logic is exposed over HTTP via `POST /instruments/sync/binanceus`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from packages.adapters.crypto.binance_universe import (
    BinanceInstrument,
    fetch_universe,
)
from packages.backtest.historical_backfill import _build_db_url

_UPSERT_SQL = text(
    """
    INSERT INTO instruments
        (asset_class, canonical_symbol, venue, native_symbol, base, quote,
         metadata, active)
    VALUES
        ('crypto_spot', :canonical_symbol, 'BINANCEUS', :native_symbol,
         :base, :quote, CAST(:metadata AS JSONB), :active)
    ON CONFLICT (canonical_symbol) DO UPDATE SET
        native_symbol = EXCLUDED.native_symbol,
        base = EXCLUDED.base,
        quote = EXCLUDED.quote,
        metadata = instruments.metadata || EXCLUDED.metadata
    """
)


async def sync_universe(
    conn: AsyncConnection,
    universe: list[BinanceInstrument],
    *,
    activate: bool = False,
) -> dict[str, int]:
    """Upsert a universe into the instruments table.

    When ``activate`` is True, inserted rows are created with active=TRUE.
    Existing rows' active flag is never changed here (toggle via the API), so
    a one-time bulk import doesn't silently start ingesting hundreds of pairs.

    Returns counts: {"inserted_or_updated": N}.
    """
    import json

    rows = [
        {
            "canonical_symbol": i.canonical_symbol,
            "native_symbol": i.native_symbol,
            "base": i.base,
            "quote": i.quote,
            "metadata": json.dumps(
                {
                    "status": i.status,
                    "base_precision": i.base_precision,
                    "quote_precision": i.quote_precision,
                }
            ),
            "active": activate,
        }
        for i in universe
    ]
    if not rows:
        return {"inserted_or_updated": 0}
    await conn.execute(_UPSERT_SQL, rows)
    return {"inserted_or_updated": len(rows)}


async def main_async(args: argparse.Namespace) -> int:
    quote_assets: set[str] | None = None
    if args.quote:
        quote_assets = {q.strip().upper() for q in args.quote.split(",") if q.strip()}

    print("Fetching Binance.US exchangeInfo ...")
    universe = await fetch_universe(trading_only=True, quote_assets=quote_assets)
    print(f"  {len(universe)} TRADING spot pairs"
          + (f" (quote in {sorted(quote_assets)})" if quote_assets else ""))

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            result = await sync_universe(conn, universe, activate=args.activate)
        print(f"Upserted {result['inserted_or_updated']} instruments "
              f"(active={args.activate}).")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quote",
        default=None,
        help="Comma-separated quote assets to keep (e.g. 'USDT,USD,USDC'). "
             "Default: all quote assets.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Mark newly-inserted instruments active (eligible for ingestion).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
