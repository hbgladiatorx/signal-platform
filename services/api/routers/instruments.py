"""Instrument catalog endpoints.

GET /instruments                           — list all active instruments
GET /instruments/{canonical_symbol}        — single instrument lookup

Both endpoints require a valid JWT.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import Instrument
from packages.core.types import AssetClass
from services.api.auth import get_current_user
from services.api.deps import get_db_session

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[Instrument])
async def list_instruments(
    venue: str | None = Query(default=None, description="Filter by venue (e.g., BINANCEUS)"),
    asset_class: AssetClass | None = Query(default=None, description="Filter by asset class"),
    active: bool = Query(default=True, description="Only active instruments"),
    session: AsyncSession = Depends(get_db_session),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[Instrument]:
    """List instruments with optional venue and asset-class filters."""
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


@router.get("/{canonical_symbol}", response_model=Instrument)
async def get_instrument(
    canonical_symbol: str,
    session: AsyncSession = Depends(get_db_session),
    _user: dict[str, Any] = Depends(get_current_user),
) -> Instrument:
    """Look up a single instrument by its canonical symbol."""
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
