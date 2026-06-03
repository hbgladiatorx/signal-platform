"""Load per-symbol instrument metadata for a backtest run.

Backtests are symbol-agnostic by default (multiplier 1, bps fees). For options
the engine needs the contract multiplier and expiry/right/strike to settle
positions at expiry; this loader pulls that from the instruments table and
returns a mapping the engine consumes via ``BacktestConfig.instrument_meta``.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.backtest.types import InstrumentMeta


async def load_instrument_meta(
    engine: AsyncEngine, symbols: list[str]
) -> dict[str, InstrumentMeta]:
    """Return canonical_symbol -> InstrumentMeta for the given symbols.

    Only rows that carry non-default metadata (options, or multiplier != 1) are
    interesting, but we return meta for every requested symbol that exists so the
    engine can look up multipliers uniformly.
    """
    if not symbols:
        return {}
    out: dict[str, InstrumentMeta] = {}
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT canonical_symbol, asset_class, "
                "COALESCE(multiplier, 1) AS multiplier, "
                "expiry, option_right, strike, underlying "
                "FROM instruments WHERE canonical_symbol = ANY(:syms)"
            ),
            {"syms": symbols},
        )
        for row in result.mappings():
            out[row["canonical_symbol"]] = InstrumentMeta(
                multiplier=Decimal(str(row["multiplier"])),
                asset_class=row["asset_class"],
                expiry=row["expiry"],
                right=row["option_right"],
                strike=Decimal(str(row["strike"])) if row["strike"] is not None else None,
                underlying=row["underlying"],
            )
    return out
