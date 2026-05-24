"""Strategies endpoint.

GET /strategies         — list built-in + user strategies for the current user
GET /strategies/{name}  — get one (built-in or user)

The built-in list is discovered once per process at module import via
packages.strategy.registry.discover_strategies(). To pick up new
built-in strategies, the API container must restart. User strategies
are loaded from the database on every request.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.user_strategies import (
    get_user_strategy_by_name,
    list_user_strategies_for_user,
)
from packages.strategy.base import Strategy
from packages.strategy.registry import discover_strategies
from services.api.deps import (
    CurrentUserRecord,
    get_current_user_record,
    get_db_session,
)


router = APIRouter(prefix="/strategies", tags=["strategies"])


STRATEGIES_DIR = Path("/app/strategies")

# Process-level cache of built-in strategies. Refreshed on container restart.
_strategies_cache: dict[str, type[Strategy]] | None = None


def get_strategy_registry() -> dict[str, type[Strategy]]:
    """Lazy-init, process-level built-in registry."""
    global _strategies_cache
    if _strategies_cache is None:
        _strategies_cache = discover_strategies(STRATEGIES_DIR)
    return _strategies_cache


class StrategyInfo(BaseModel):
    name: str
    description: str
    params_schema: dict[str, Any]
    source: Literal["built-in", "user"]
    user_strategy_id: Optional[UUID] = None


# ============================================================
# Endpoints
# ============================================================

@router.get("", response_model=list[StrategyInfo])
async def list_strategies(
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[StrategyInfo]:
    """List built-in strategies plus the current user's user-authored strategies.

    Built-ins are sorted alphabetically, then user strategies sorted by name.
    The `source` field distinguishes them; `user_strategy_id` is set only
    for user-authored entries.
    """
    # Built-ins
    registry = get_strategy_registry()
    items: list[StrategyInfo] = [
        StrategyInfo(
            name=cls.name(),
            description=cls.description(),
            params_schema=cls.params_schema(),
            source="built-in",
        )
        for cls in sorted(registry.values(), key=lambda c: c.name())
    ]

    # User strategies
    user_rows = await list_user_strategies_for_user(session, user_id=user.id)
    for row in sorted(user_rows, key=lambda r: r["name"]):
        items.append(
            StrategyInfo(
                name=row["name"],
                description=row.get("description") or "",
                params_schema=row["params_schema"],
                source="user",
                user_strategy_id=row["id"],
            )
        )

    return items


@router.get("/{name}", response_model=StrategyInfo)
async def get_strategy(
    name: str,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> StrategyInfo:
    """Get a single strategy by name (built-in or user-authored)."""
    # Built-in first
    registry = get_strategy_registry()
    cls = registry.get(name)
    if cls is not None:
        return StrategyInfo(
            name=cls.name(),
            description=cls.description(),
            params_schema=cls.params_schema(),
            source="built-in",
        )

    # User strategy
    row = await get_user_strategy_by_name(session, user_id=user.id, name=name)
    if row is not None:
        return StrategyInfo(
            name=row["name"],
            description=row.get("description") or "",
            params_schema=row["params_schema"],
            source="user",
            user_strategy_id=row["id"],
        )

    raise HTTPException(
        status_code=404,
        detail=f"Strategy not found: {name}",
    )
