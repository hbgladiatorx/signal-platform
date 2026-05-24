"""Strategies endpoint.

GET /strategies — list available strategies with their params schemas.

The strategy list is discovered once per process at module import via
packages.strategy.registry.discover_strategies(). To pick up new
strategies, the API container must restart.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from packages.strategy.base import Strategy
from packages.strategy.registry import discover_strategies
from services.api.auth import get_current_user


router = APIRouter(prefix="/strategies", tags=["strategies"])


STRATEGIES_DIR = Path("/app/strategies")

# Process-level cache. Refreshed on container restart.
_strategies_cache: dict[str, type[Strategy]] | None = None


def get_strategy_registry() -> dict[str, type[Strategy]]:
    """Lazy-init, process-level strategy registry."""
    global _strategies_cache
    if _strategies_cache is None:
        _strategies_cache = discover_strategies(STRATEGIES_DIR)
    return _strategies_cache


class StrategyInfo(BaseModel):
    name: str
    description: str
    params_schema: dict[str, Any]


@router.get("", response_model=list[StrategyInfo])
async def list_strategies(
    _user: dict = Depends(get_current_user),
) -> list[StrategyInfo]:
    """List discovered strategies and their parameter schemas.

    The frontend uses params_schema to render a configuration form via
    JSON-Schema-driven generation.
    """
    registry = get_strategy_registry()
    return [
        StrategyInfo(
            name=cls.name(),
            description=cls.description(),
            params_schema=cls.params_schema(),
        )
        for cls in sorted(registry.values(), key=lambda c: c.name())
    ]


@router.get("/{name}", response_model=StrategyInfo)
async def get_strategy(
    name: str,
    _user: dict = Depends(get_current_user),
) -> StrategyInfo:
    """Get a single strategy by name."""
    registry = get_strategy_registry()
    cls = registry.get(name)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy not found: {name}",
        )
    return StrategyInfo(
        name=cls.name(),
        description=cls.description(),
        params_schema=cls.params_schema(),
    )
