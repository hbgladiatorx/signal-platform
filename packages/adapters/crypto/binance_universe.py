"""Binance.US universe loader.

Phase 1 hardcoded a 2-symbol native↔canonical table inside the adapter.
This module replaces that with the *full* Binance.US spot universe, fetched
from the public `exchangeInfo` REST endpoint and cached in memory.

The universe is the source of truth for two things:

  1. Symbol translation — every TRADING spot pair on Binance.US, in both
     directions (``BTCUSDT`` ↔ ``BTC-USDT@BINANCEUS``). Unlike a naive
     ``base+quote`` concatenation, the canonical split is unambiguous because
     Binance gives us ``baseAsset`` and ``quoteAsset`` explicitly.

  2. Instrument catalog population — the sync script (``binance_universe_sync``)
     and the API ``POST /instruments/sync/binanceus`` endpoint both consume
     :func:`fetch_universe` to upsert rows into the ``instruments`` table so
     backtesting, paper, and live trading can reference any pair.

Nothing here touches the database; it is pure HTTP + parsing so it can be
unit-tested and reused from any service.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp

from packages.core.exceptions import AdapterError

EXCHANGE_INFO_URL = "https://api.binance.us/api/v3/exchangeInfo"
HTTP_TIMEOUT_S = 30
MAX_RETRIES = 4

VENUE = "BINANCEUS"


@dataclass(frozen=True)
class BinanceInstrument:
    """One spot pair as Binance.US describes it, in canonical platform form."""

    native_symbol: str       # "BTCUSDT"
    canonical_symbol: str    # "BTC-USDT@BINANCEUS"
    base: str                # "BTC"
    quote: str               # "USDT"
    status: str              # "TRADING", "BREAK", ...
    base_precision: int
    quote_precision: int

    @property
    def is_trading(self) -> bool:
        return self.status == "TRADING"


def canonical_from_parts(base: str, quote: str) -> str:
    """Build a canonical symbol from explicit base/quote assets."""
    return f"{base.upper()}-{quote.upper()}@{VENUE}"


def _parse_symbol(entry: dict[str, Any]) -> BinanceInstrument | None:
    """Translate one exchangeInfo `symbols[]` entry into a BinanceInstrument.

    Returns None for entries missing the fields we require.
    """
    native = entry.get("symbol")
    base = entry.get("baseAsset")
    quote = entry.get("quoteAsset")
    if not native or not base or not quote:
        return None
    return BinanceInstrument(
        native_symbol=native.upper(),
        canonical_symbol=canonical_from_parts(base, quote),
        base=base.upper(),
        quote=quote.upper(),
        status=str(entry.get("status", "UNKNOWN")).upper(),
        base_precision=int(entry.get("baseAssetPrecision", 8)),
        quote_precision=int(entry.get("quoteAssetPrecision", 8)),
    )


def parse_exchange_info(
    payload: dict[str, Any],
    *,
    trading_only: bool = True,
) -> list[BinanceInstrument]:
    """Parse a raw exchangeInfo payload into BinanceInstrument records."""
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise AdapterError("exchangeInfo payload missing 'symbols' array")
    out: list[BinanceInstrument] = []
    for entry in symbols:
        inst = _parse_symbol(entry)
        if inst is None:
            continue
        if trading_only and not inst.is_trading:
            continue
        out.append(inst)
    return out


async def fetch_exchange_info(
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """Fetch the raw exchangeInfo payload with bounded retries."""
    own_session = session is None
    sess = session or aiohttp.ClientSession()
    last_err: Exception | None = None
    try:
        for attempt in range(MAX_RETRIES):
            try:
                async with sess.get(
                    EXCHANGE_INFO_URL,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                ) as resp:
                    if resp.status >= 500 or resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
            except (TimeoutError, aiohttp.ClientError) as e:
                last_err = e
                await asyncio.sleep(2 ** attempt)
        raise AdapterError(
            f"Failed to fetch Binance.US exchangeInfo after {MAX_RETRIES} "
            f"attempts; last error: {last_err}"
        )
    finally:
        if own_session:
            await sess.close()


async def fetch_universe(
    *,
    trading_only: bool = True,
    quote_assets: set[str] | None = None,
    session: aiohttp.ClientSession | None = None,
) -> list[BinanceInstrument]:
    """Fetch and parse the full Binance.US spot universe.

    Args:
        trading_only: keep only pairs whose status == "TRADING".
        quote_assets: if given, keep only pairs whose quote is in this set
            (e.g. ``{"USDT", "USD", "USDC"}``). Case-insensitive.
        session: optional shared aiohttp session.
    """
    payload = await fetch_exchange_info(session)
    universe = parse_exchange_info(payload, trading_only=trading_only)
    if quote_assets:
        wanted = {q.upper() for q in quote_assets}
        universe = [i for i in universe if i.quote in wanted]
    return universe


def build_translation_maps(
    universe: list[BinanceInstrument],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (native→canonical, canonical→native) maps for a universe."""
    native_to_canonical = {i.native_symbol: i.canonical_symbol for i in universe}
    canonical_to_native = {i.canonical_symbol: i.native_symbol for i in universe}
    return native_to_canonical, canonical_to_native
