"""Polygon.io options-contract discovery (single-leg).

Pulls active option contracts for a configured set of underliers from Polygon's
reference API and upserts them into the ``instruments`` table with the option
columns (underlying / right / strike / expiry / multiplier) populated.

Scoped to an explicit underlier watchlist — the full OPRA universe is enormous
and must never be discovered wholesale.

Canonical symbol: OCC-style with the execution venue tag, e.g.
``AAPL250117C00150000@ALPACA`` (the OCC string is the Alpaca native symbol;
Polygon's ``O:``-prefixed form is kept in metadata.polygon_ticker).

Run:
    python -m packages.data.universe.polygon_options_discovery --underlying AAPL,SPY
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import date

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

CONTRACTS_URL = "https://api.polygon.io/v3/reference/options/contracts"
VENUE = "ALPACA"
ASSET_CLASS = "option"
HTTP_TIMEOUT_S = 30
PAGE_LIMIT = 1000


@dataclass
class DiscoveryReport:
    underliers: list[str]
    fetched: int
    upserted: int


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


async def fetch_contracts(
    http: aiohttp.ClientSession, api_key: str, underlying: str, *, max_per: int | None
) -> list[dict]:
    results: list[dict] = []
    params = {
        "underlying_ticker": underlying,
        "expired": "false",
        "limit": str(PAGE_LIMIT),
        "apiKey": api_key,
    }
    url: str | None = CONTRACTS_URL
    while url:
        async with http.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        results.extend(data.get("results", []) or [])
        if max_per is not None and len(results) >= max_per:
            return results[:max_per]
        url = data.get("next_url")
        params = {"apiKey": api_key}
    return results


def _to_row(c: dict) -> dict | None:
    pticker = c.get("ticker")  # 'O:AAPL250117C00150000'
    if not pticker:
        return None
    native = pticker[2:] if pticker.startswith("O:") else pticker
    underlying = c.get("underlying_ticker")
    right = "C" if c.get("contract_type") == "call" else "P"
    # Polygon returns expiration_date as an ISO string; the instruments.expiry
    # column is a DATE, and asyncpg requires a date object (not a str).
    exp_raw = c.get("expiration_date")
    expiry = date.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
    meta = {
        "data_source": "polygon",
        "polygon_ticker": pticker,
        "contract_type": c.get("contract_type"),
    }
    return {
        "asset_class": ASSET_CLASS,
        "canonical_symbol": f"{native}@{VENUE}",
        "venue": VENUE,
        "native_symbol": native,
        "base": underlying,
        "quote": "USD",
        "underlying": f"{underlying}@{VENUE}" if underlying else None,
        "option_right": right,
        "strike": c.get("strike_price"),
        "expiry": expiry,
        "multiplier": c.get("shares_per_contract") or 100,
        "metadata": json.dumps(meta),
    }


async def discover_polygon_options(
    engine: AsyncEngine,
    underliers: list[str],
    *,
    max_per: int | None = None,
    dry_run: bool = False,
) -> DiscoveryReport:
    api_key = _api_key()
    rows: list[dict] = []
    fetched = 0
    async with aiohttp.ClientSession() as http:
        for u in underliers:
            contracts = await fetch_contracts(http, api_key, u, max_per=max_per)
            fetched += len(contracts)
            for c in contracts:
                r = _to_row(c)
                if r:
                    rows.append(r)

    if dry_run:
        return DiscoveryReport(underliers=underliers, fetched=fetched, upserted=len(rows))

    async with engine.begin() as conn:
        for i in range(0, len(rows), 1000):
            await conn.execute(
                text(
                    """
                    INSERT INTO instruments
                        (asset_class, canonical_symbol, venue, native_symbol, base, quote,
                         underlying, option_right, strike, expiry, multiplier, metadata, active)
                    VALUES
                        (:asset_class, :canonical_symbol, :venue, :native_symbol, :base, :quote,
                         :underlying, :option_right, :strike, :expiry, :multiplier,
                         CAST(:metadata AS JSONB), TRUE)
                    ON CONFLICT (canonical_symbol) DO UPDATE SET
                        underlying = EXCLUDED.underlying,
                        option_right = EXCLUDED.option_right,
                        strike = EXCLUDED.strike,
                        expiry = EXCLUDED.expiry,
                        multiplier = EXCLUDED.multiplier,
                        metadata = instruments.metadata || EXCLUDED.metadata,
                        active = TRUE
                    """
                ),
                rows[i : i + 1000],
            )

    return DiscoveryReport(underliers=underliers, fetched=fetched, upserted=len(rows))


async def _main(args: argparse.Namespace) -> int:
    underliers = [u.strip().upper() for u in args.underlying.split(",") if u.strip()]
    if not underliers:
        raise SystemExit("--underlying is required (comma-separated tickers)")
    engine = create_async_engine(_build_db_url(), pool_pre_ping=True)
    try:
        report = await discover_polygon_options(
            engine, underliers, max_per=args.max_per, dry_run=args.dry_run
        )
    finally:
        await engine.dispose()
    print(
        f"Polygon options discovery: underliers={report.underliers} "
        f"fetched={report.fetched} upserted={report.upserted} dry_run={args.dry_run}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Polygon option contracts")
    parser.add_argument("--underlying", required=True, help="comma-separated underliers, e.g. AAPL,SPY")
    parser.add_argument("--max-per", type=int, default=None, help="cap contracts per underlier")
    parser.add_argument("--dry-run", action="store_true")
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
