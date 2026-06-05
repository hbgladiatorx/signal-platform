"""Re-materialize the cagg chain for an already-ingested window.

Use when a symbol's synthetic trades are present (e.g. a prior backfill loaded
them) but one or more `cagg_bars_*` resolutions are missing because the original
`refresh_caggs` was interrupted partway through the dependency chain.

This re-runs the SAME refresh_caggs() used by the backfill tools over the given
date range; it does NOT fetch any external data. Safe to re-run (idempotent).

Run:
    python -m packages.backtest.sources.refresh_symbol_caggs \
        --start 2024-01-01 --end 2025-01-01
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine

from packages.backtest.historical_backfill import refresh_caggs


def _build_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def main_async(args: argparse.Namespace) -> int:
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError(f"--end ({args.end}) must be after --start ({args.start})")
    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    try:
        await refresh_caggs(engine, start, end)
        print("DONE")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh cagg chain over a window")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
