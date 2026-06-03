"""SymbolRegistry — instruments-table-backed symbol translation.

Replaces the per-adapter hardcoded native<->canonical lookup tables (the
Phase 1 ``_NATIVE_TO_CANONICAL`` dicts) with a single source of truth: the
``instruments`` table. Loaded once at service startup (and optionally refreshed)
so the tradable universe can grow without code changes.

Adapters stay free of DB access: a service loads a ``SymbolRegistry`` and injects
it into the adapter. When no registry is injected (e.g. unit tests), adapters
fall back to mechanical symbol splitting.

Usage:
    registry = await SymbolRegistry.load(engine, venue="BINANCEUS")
    registry.to_canonical("BTCUSDT", "BINANCEUS")   # 'BTC-USDT@BINANCEUS'
    registry.to_native("BTC-USDT@BINANCEUS")        # 'BTCUSDT'
    registry.canonicals_for_venue("BINANCEUS")      # ['BTC-USDT@BINANCEUS', ...]
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class InstrumentRow:
    id: int
    asset_class: str
    canonical_symbol: str
    venue: str
    native_symbol: str
    base: str | None = None
    quote: str | None = None
    metadata: dict = field(default_factory=dict)
    active: bool = True


class SymbolRegistry:
    """Bidirectional native<->canonical maps loaded from the instruments table."""

    def __init__(self, rows: list[InstrumentRow]) -> None:
        self._rows = rows
        # (venue, native_upper) -> canonical
        self._native_to_canonical: dict[tuple[str, str], str] = {}
        # canonical -> row
        self._by_canonical: dict[str, InstrumentRow] = {}
        for r in rows:
            self._by_canonical[r.canonical_symbol] = r
            self._native_to_canonical[(r.venue.upper(), r.native_symbol.upper())] = (
                r.canonical_symbol
            )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    @classmethod
    async def load(
        cls,
        engine: AsyncEngine,
        *,
        venue: str | None = None,
        asset_class: str | None = None,
        active_only: bool = True,
    ) -> "SymbolRegistry":
        """Load instruments into a registry, optionally filtered by venue/class."""
        clauses: list[str] = []
        params: dict[str, object] = {}
        if active_only:
            clauses.append("active = TRUE")
        if venue is not None:
            clauses.append("venue = :venue")
            params["venue"] = venue
        if asset_class is not None:
            clauses.append("asset_class = :asset_class")
            params["asset_class"] = asset_class
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        rows: list[InstrumentRow] = []
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, asset_class, canonical_symbol, venue, native_symbol, "
                    "base, quote, metadata, active FROM instruments" + where
                ),
                params,
            )
            for row in result.mappings():
                rows.append(
                    InstrumentRow(
                        id=row["id"],
                        asset_class=row["asset_class"],
                        canonical_symbol=row["canonical_symbol"],
                        venue=row["venue"],
                        native_symbol=row["native_symbol"],
                        base=row["base"],
                        quote=row["quote"],
                        metadata=row["metadata"] or {},
                        active=row["active"],
                    )
                )
        return cls(rows)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------
    def to_canonical(self, native: str, venue: str) -> str:
        """Native -> canonical. Raises KeyError if unknown."""
        return self._native_to_canonical[(venue.upper(), native.upper())]

    def to_canonical_or_none(self, native: str, venue: str) -> str | None:
        return self._native_to_canonical.get((venue.upper(), native.upper()))

    def to_native(self, canonical: str) -> str:
        """Canonical -> native. Raises KeyError if unknown."""
        return self._by_canonical[canonical].native_symbol

    def row(self, canonical: str) -> InstrumentRow | None:
        return self._by_canonical.get(canonical)

    def instrument_id(self, canonical: str) -> int | None:
        r = self._by_canonical.get(canonical)
        return r.id if r is not None else None

    def canonicals_for_venue(self, venue: str) -> list[str]:
        v = venue.upper()
        return [r.canonical_symbol for r in self._rows if r.venue.upper() == v]

    def __len__(self) -> int:
        return len(self._rows)
