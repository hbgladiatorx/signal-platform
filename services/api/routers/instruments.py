"""Instrument catalog endpoints.

GET  /instruments                           — list all instruments (with optional filters)
GET  /instruments/{canonical_symbol}        — single instrument lookup
POST /instruments                           — add a new instrument (after venue verification)
PUT  /instruments/{canonical_symbol}/active — toggle the active flag

The POST endpoint verifies the symbol exists on the venue's exchange
before inserting. The PATCH endpoint updates the active flag only.

Phase 1: single-org platform, so the instruments table IS the user's
tracked set. Phase 2+ may introduce per-user/per-org tracked subsets.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import Instrument
from packages.core.types import AssetClass
from services.api.auth import get_current_user
from services.api.deps import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instruments", tags=["instruments"])


# ============================================================
# Existing GETs (preserved verbatim from Step 7)
# ============================================================


@router.get("", response_model=list[Instrument])
async def list_instruments(
    venue: str | None = Query(default=None, description="Filter by venue (e.g., BINANCEUS)"),
    asset_class: AssetClass | None = Query(default=None, description="Filter by asset class"),
    active: bool | None = Query(
        default=True,
        description="Filter by active flag. Pass active=null in URL via no parameter; "
                    "passing 'active=false' returns inactive only; default returns active only.",
    ),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> list[Instrument]:
    """List instruments with optional filters."""
    query = """
        SELECT id, asset_class, canonical_symbol, venue, native_symbol,
               base, quote, metadata, active
        FROM instruments
        WHERE 1=1
    """
    params: dict = {}

    if active is not None:
        query += " AND active = :active"
        params["active"] = active
    if venue is not None:
        query += " AND venue = :venue"
        params["venue"] = venue
    if asset_class is not None:
        query += " AND asset_class = :asset_class"
        params["asset_class"] = asset_class.value

    query += " ORDER BY canonical_symbol"

    result = await session.execute(text(query), params)
    return [Instrument.model_validate(row) for row in result.mappings()]


class InstrumentCoverage(BaseModel):
    canonical_symbol: str
    bars: int
    first: str | None = None
    last: str | None = None


@router.get("/coverage", response_model=list[InstrumentCoverage])
async def instrument_coverage(
    asset_class: AssetClass | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> list[InstrumentCoverage]:
    """How much historical data each instrument actually has (daily-bar proxy).

    The frontend uses this to pick symbols that are tradeable in a backtest:
    most of the 256 crypto instruments have little or no history, so picking
    by name alone (or alphabetical fallback) silently runs a strategy on a
    symbol with no data → zero trades. Daily caggs are the cheapest proxy for
    "this symbol has a usable history" and `bars`/`first`/`last` let the UI
    sort, default, and warn. Only instruments with ≥1 daily bar are returned.
    """
    query = """
        SELECT i.canonical_symbol AS canonical_symbol,
               COUNT(*)            AS bars,
               MIN(c.bucket)       AS first,
               MAX(c.bucket)       AS last
        FROM cagg_bars_1d c
        JOIN instruments i ON i.id = c.instrument_id
        WHERE 1=1
    """
    params: dict = {}
    if asset_class is not None:
        query += " AND i.asset_class = :asset_class"
        params["asset_class"] = asset_class.value
    query += " GROUP BY i.canonical_symbol ORDER BY bars DESC"

    result = await session.execute(text(query), params)
    out: list[InstrumentCoverage] = []
    for row in result.mappings():
        out.append(
            InstrumentCoverage(
                canonical_symbol=row["canonical_symbol"],
                bars=int(row["bars"]),
                first=row["first"].isoformat() if row["first"] else None,
                last=row["last"].isoformat() if row["last"] else None,
            )
        )
    return out


@router.get("/{canonical_symbol}", response_model=Instrument)
async def get_instrument(
    canonical_symbol: str,
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> Instrument:
    """Look up a single instrument by canonical symbol."""
    result = await session.execute(
        text(
            """
            SELECT id, asset_class, canonical_symbol, venue, native_symbol,
                   base, quote, metadata, active
            FROM instruments
            WHERE canonical_symbol = :canonical_symbol
            """
        ),
        {"canonical_symbol": canonical_symbol},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {canonical_symbol}",
        )
    return Instrument.model_validate(row)


# ============================================================
# Step 14 additions
# ============================================================


class ActiveToggleRequest(BaseModel):
    active: bool


class InstrumentCreateRequest(BaseModel):
    """
    A user-supplied instrument descriptor.

    The backend validates that the symbol exists on the venue's exchange
    before inserting. Canonical symbol is computed server-side.
    """

    asset_class: AssetClass
    venue: str = Field(..., min_length=2, max_length=32, pattern=r"^[A-Z0-9_]+$")
    base: str = Field(..., min_length=1, max_length=16)
    quote: str = Field(..., min_length=1, max_length=16)


async def _verify_binanceus_symbol(base: str, quote: str) -> str:
    """
    Hit Binance.US /api/v3/exchangeInfo to verify the pair exists.
    Returns the native symbol (e.g. 'BTCUSDT') on success.
    Raises HTTPException on any failure.
    """
    native = f"{base.upper()}{quote.upper()}"
    url = f"https://api.binance.us/api/v3/exchangeInfo?symbol={native}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        logger.warning("binanceus.exchangeinfo.network_error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Could not reach Binance.US to verify the symbol",
        )

    if resp.status_code == 400:
        # Binance.US returns 400 with code -1121 for unknown symbol
        raise HTTPException(
            status_code=400,
            detail=f"Symbol {native} is not listed on Binance.US",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Binance.US returned HTTP {resp.status_code} while verifying {native}",
        )

    try:
        data = resp.json()
        symbols = data.get("symbols", [])
        if not symbols:
            raise HTTPException(
                status_code=400,
                detail=f"Binance.US has no listing for {native}",
            )
        symbol_info = symbols[0]
        if symbol_info.get("status") != "TRADING":
            raise HTTPException(
                status_code=400,
                detail=f"{native} exists on Binance.US but is not currently TRADING "
                       f"(status: {symbol_info.get('status')})",
            )
        return symbol_info["symbol"]
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not parse Binance.US response: {exc}",
        )


@router.post("", response_model=Instrument, status_code=201)
async def create_instrument(
    body: InstrumentCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> Instrument:
    """
    Add a new instrument after verifying it exists on the venue.

    Phase 1 supports only BINANCEUS as the venue. Other venues will
    be added with their own adapters in later phases.
    """
    venue = body.venue.upper()
    base = body.base.upper()
    quote = body.quote.upper()

    if venue != "BINANCEUS":
        raise HTTPException(
            status_code=400,
            detail=f"Venue '{venue}' is not supported in Phase 1. "
                   f"Supported venues: ['BINANCEUS']",
        )

    if body.asset_class != AssetClass.CRYPTO_SPOT:
        raise HTTPException(
            status_code=400,
            detail=f"Asset class '{body.asset_class}' is not supported for Binance.US. "
                   f"Use 'crypto_spot'.",
        )

    # Verify on exchange before INSERT
    native_symbol = await _verify_binanceus_symbol(base, quote)
    canonical_symbol = f"{base}-{quote}@{venue}"

    try:
        result = await session.execute(
            text(
                """
                INSERT INTO instruments
                    (asset_class, canonical_symbol, venue, native_symbol,
                     base, quote, metadata, active)
                VALUES
                    (:asset_class, :canonical_symbol, :venue, :native_symbol,
                     :base, :quote, '{}'::jsonb, TRUE)
                RETURNING id, asset_class, canonical_symbol, venue, native_symbol,
                          base, quote, metadata, active
                """
            ),
            {
                "asset_class": body.asset_class.value,
                "canonical_symbol": canonical_symbol,
                "venue": venue,
                "native_symbol": native_symbol,
                "base": base,
                "quote": quote,
            },
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        err_text = str(exc).lower()
        if "duplicate key" in err_text or "unique" in err_text:
            raise HTTPException(
                status_code=409,
                detail=f"Instrument {canonical_symbol} already exists",
            )
        raise

    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="Insert returned no row")
    return Instrument.model_validate(row)


@router.put("/{canonical_symbol}/active", response_model=Instrument)
async def toggle_instrument_active(
    canonical_symbol: str,
    body: ActiveToggleRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(get_current_user),
) -> Instrument:
    """Set the `active` flag on an instrument."""
    result = await session.execute(
        text(
            """
            UPDATE instruments
            SET active = :active
            WHERE canonical_symbol = :canonical_symbol
            RETURNING id, asset_class, canonical_symbol, venue, native_symbol,
                      base, quote, metadata, active
            """
        ),
        {"canonical_symbol": canonical_symbol, "active": body.active},
    )
    await session.commit()
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {canonical_symbol}",
        )
    return Instrument.model_validate(row)
