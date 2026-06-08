"""Binance.US universe discovery.

Pulls the full set of actively-trading spot pairs from Binance.US's
``exchangeInfo`` endpoint and upserts them into the ``instruments`` table, so
the ingestion/backtest/trade stack can operate across the entire venue rather
than a hardcoded handful of pairs.

Pairs no longer TRADING are marked ``active = FALSE`` (de-listing handling)
rather than deleted, preserving historical bars/trades and their FKs.

Run (one-shot, inside any service container that has DB access):
    python -m packages.data.universe.binanceus_discovery --quote USDT,USD,USDC
    python -m packages.data.universe.binanceus_discovery --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

EXCHANGE_INFO_URL = "https://api.binance.us/api/v3/exchangeInfo"
VENUE = "BINANCEUS"
ASSET_CLASS = "crypto_spot"
HTTP_TIMEOUT_S = 30


@dataclass
class DiscoveryReport:
    fetched: int
    upserted: int
    deactivated: int
    quote_filter: list[str] | None


def _build_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def fetch_exchange_info(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(
        EXCHANGE_INFO_URL, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
    return data.get("symbols", [])


def _to_rows(
    symbols: list[dict], quote_allowlist: set[str] | None
) -> list[dict]:
    rows: list[dict] = []
    for s in symbols:
        if s.get("status") != "TRADING":
            continue
        base = s.get("baseAsset")
        quote = s.get("quoteAsset")
        native = s.get("symbol")
        if not (base and quote and native):
            continue
        if quote_allowlist and quote.upper() not in quote_allowlist:
            continue
        rows.append(
            {
                "asset_class": ASSET_CLASS,
                "canonical_symbol": f"{base}-{quote}@{VENUE}",
                "venue": VENUE,
                "native_symbol": native,
                "base": base,
                "quote": quote,
            }
        )
    return rows


async def discover_binanceus_universe(
    engine: AsyncEngine,
    *,
    quote_allowlist: set[str] | None = None,
    dry_run: bool = False,
) -> DiscoveryReport:
    async with aiohttp.ClientSession() as http:
        symbols = await fetch_exchange_info(http)
    rows = _to_rows(symbols, quote_allowlist)

    if dry_run:
        return DiscoveryReport(
            fetched=len(symbols),
            upserted=len(rows),
            deactivated=0,
            quote_filter=sorted(quote_allowlist) if quote_allowlist else None,
        )

    canonicals = [r["canonical_symbol"] for r in rows]
    async with engine.begin() as conn:
        if rows:
            await conn.execute(
                text(
                    """
                    INSERT INTO instruments
                        (asset_class, canonical_symbol, venue, native_symbol, base, quote, active)
                    VALUES
                        (:asset_class, :canonical_symbol, :venue, :native_symbol, :base, :quote, TRUE)
                    ON CONFLICT (canonical_symbol) DO UPDATE SET
                        native_symbol = EXCLUDED.native_symbol,
                        base = EXCLUDED.base,
                        quote = EXCLUDED.quote,
                        active = TRUE
                    """
                ),
                rows,
            )
        # Deactivate Binance.US spot instruments that are no longer trading.
        result = await conn.execute(
            text(
                """
                UPDATE instruments
                   SET active = FALSE
                 WHERE venue = :venue
                   AND asset_class = :asset_class
                   AND active = TRUE
                   AND NOT (canonical_symbol = ANY(:keep))
                """
            ),
            {"venue": VENUE, "asset_class": ASSET_CLASS, "keep": canonicals},
        )
        deactivated = result.rowcount or 0

    return DiscoveryReport(
        fetched=len(symbols),
        upserted=len(rows),
        deactivated=deactivated,
        quote_filter=sorted(quote_allowlist) if quote_allowlist else None,
    )


async def _main(args: argparse.Namespace) -> int:
    quote_allowlist: set[str] | None = None
    if args.quote:
        quote_allowlist = {q.strip().upper() for q in args.quote.split(",") if q.strip()}

    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    try:
        report = await discover_binanceus_universe(
            engine, quote_allowlist=quote_allowlist, dry_run=args.dry_run
        )
    finally:
        await engine.dispose()

    print(
        f"Binance.US discovery: fetched={report.fetched} "
        f"trading_upserted={report.upserted} deactivated={report.deactivated} "
        f"quote_filter={report.quote_filter} dry_run={args.dry_run}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover the Binance.US spot universe")
    parser.add_argument(
        "--quote",
        default="USDT,USD,USDC",
        help="comma-separated quote-asset allowlist (default USDT,USD,USDC; "
        "pass empty string to include all quotes)",
    )
    parser.add_argument("--dry-run", action="store_true", help="fetch + count only")
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
