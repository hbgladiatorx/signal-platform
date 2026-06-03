"""Polygon.io stock-universe discovery.

Pulls the active US common-stock universe from Polygon's reference API and
upserts it into the ``instruments`` table. Symbols keep the EXECUTION venue tag
(``AAPL@ALPACA``) so Polygon-sourced bars and Alpaca-routed orders share one
instrument row; the data origin is recorded in ``metadata.data_source``.

Run:
    python -m packages.data.universe.polygon_stocks_discovery --dry-run
    python -m packages.data.universe.polygon_stocks_discovery --max 5000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TICKERS_URL = "https://api.polygon.io/v3/reference/tickers"
VENUE = "ALPACA"
ASSET_CLASS = "equity"
HTTP_TIMEOUT_S = 30
PAGE_LIMIT = 1000


@dataclass
class DiscoveryReport:
    fetched: int
    upserted: int
    deactivated: int


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


async def fetch_all_tickers(
    http: aiohttp.ClientSession, api_key: str, *, max_tickers: int | None
) -> list[dict]:
    """Page through active US stock tickers (cursor pagination via next_url)."""
    results: list[dict] = []
    params = {
        "market": "stocks",
        "type": "CS",  # common stock
        "active": "true",
        "limit": str(PAGE_LIMIT),
        "apiKey": api_key,
    }
    url: str | None = TICKERS_URL
    while url:
        async with http.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        results.extend(data.get("results", []))
        if max_tickers is not None and len(results) >= max_tickers:
            return results[:max_tickers]
        next_url = data.get("next_url")
        if not next_url:
            break
        # next_url carries the cursor; apiKey must be re-appended, other params drop.
        url = next_url
        params = {"apiKey": api_key}
    return results


def _to_rows(tickers: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for t in tickers:
        sym = t.get("ticker")
        if not sym:
            continue
        meta = {
            "data_source": "polygon",
            "polygon_ticker": sym,
            "name": t.get("name"),
            "primary_exchange": t.get("primary_exchange"),
        }
        rows.append(
            {
                "asset_class": ASSET_CLASS,
                "canonical_symbol": f"{sym}@{VENUE}",
                "venue": VENUE,
                "native_symbol": sym,
                "base": sym,
                "quote": "USD",
                "metadata": json.dumps(meta),
            }
        )
    return rows


async def discover_polygon_stock_universe(
    engine: AsyncEngine,
    *,
    max_tickers: int | None = None,
    dry_run: bool = False,
) -> DiscoveryReport:
    api_key = _api_key()
    async with aiohttp.ClientSession() as http:
        tickers = await fetch_all_tickers(http, api_key, max_tickers=max_tickers)
    rows = _to_rows(tickers)

    if dry_run:
        return DiscoveryReport(fetched=len(tickers), upserted=len(rows), deactivated=0)

    canonicals = [r["canonical_symbol"] for r in rows]
    async with engine.begin() as conn:
        # Insert in batches to keep statements reasonable.
        for i in range(0, len(rows), 1000):
            await conn.execute(
                text(
                    """
                    INSERT INTO instruments
                        (asset_class, canonical_symbol, venue, native_symbol, base, quote, metadata, active)
                    VALUES
                        (:asset_class, :canonical_symbol, :venue, :native_symbol, :base, :quote,
                         CAST(:metadata AS JSONB), TRUE)
                    ON CONFLICT (canonical_symbol) DO UPDATE SET
                        native_symbol = EXCLUDED.native_symbol,
                        metadata = instruments.metadata || EXCLUDED.metadata,
                        active = TRUE
                    """
                ),
                rows[i : i + 1000],
            )
        # Deactivate Polygon-sourced equities no longer in the active set.
        result = await conn.execute(
            text(
                """
                UPDATE instruments
                   SET active = FALSE
                 WHERE venue = :venue
                   AND asset_class = :asset_class
                   AND active = TRUE
                   AND metadata->>'data_source' = 'polygon'
                   AND NOT (canonical_symbol = ANY(:keep))
                """
            ),
            {"venue": VENUE, "asset_class": ASSET_CLASS, "keep": canonicals},
        )
        deactivated = result.rowcount or 0

    return DiscoveryReport(
        fetched=len(tickers), upserted=len(rows), deactivated=deactivated
    )


async def _main(args: argparse.Namespace) -> int:
    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    try:
        report = await discover_polygon_stock_universe(
            engine, max_tickers=args.max, dry_run=args.dry_run
        )
    finally:
        await engine.dispose()
    print(
        f"Polygon stock discovery: fetched={report.fetched} "
        f"upserted={report.upserted} deactivated={report.deactivated} "
        f"dry_run={args.dry_run}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover the Polygon US stock universe")
    parser.add_argument("--max", type=int, default=None, help="cap number of tickers")
    parser.add_argument("--dry-run", action="store_true", help="fetch + count only")
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
