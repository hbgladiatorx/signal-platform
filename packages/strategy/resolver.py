"""
Strategy resolver.

Maps a strategy name to a runnable Strategy class. The lookup order is:

  1. Built-in registry (the dict of strategies discovered from the
     `strategies/` directory at process startup)
  2. The calling user's `user_strategies` rows (active only)

A user cannot shadow a built-in: the create endpoint in
`services/api/routers/user_strategies.py` rejects names that already
exist in the registry. So lookup order matters only for "user has no
matching strategy" vs "no such strategy anywhere" disambiguation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Type
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.user_strategies import get_user_strategy_by_name
from packages.strategy.base import Strategy
from packages.strategy.loader import StrategyLoadError, load_user_strategy_class


class StrategyNotFoundError(Exception):
    """Raised when no strategy matches the given name for the user."""


@dataclass
class ResolvedStrategy:
    """A strategy ready to be instantiated and run."""
    cls: Type[Strategy]
    name: str
    description: str
    params_schema: dict[str, Any]
    source: Literal["built-in", "user"]
    user_strategy_id: UUID | None = None  # only for source == "user"


async def resolve_strategy(
    session: AsyncSession,
    *,
    user_id: UUID,
    strategy_name: str,
    builtin_registry: dict[str, Type[Strategy]],
) -> ResolvedStrategy:
    """
    Resolve a strategy name into a runnable class.

    Args:
        session: open AsyncSession (for the user_strategies fallback)
        user_id: the calling user; user_strategies are scoped to this id
        strategy_name: the name as provided by the user / stored in the
            backtest row
        builtin_registry: the caller's cached built-in registry
            (api strategies router or worker startup cache)

    Returns:
        ResolvedStrategy with the class + metadata.

    Raises:
        StrategyNotFoundError: not found in either source
        StrategyLoadError: found in user_strategies but failed to compile
    """
    # ---- 1. Built-in registry ----
    builtin_cls = builtin_registry.get(strategy_name)
    if builtin_cls is not None:
        return ResolvedStrategy(
            cls=builtin_cls,
            name=builtin_cls.name(),
            description=builtin_cls.description(),
            params_schema=builtin_cls.params_schema(),
            source="built-in",
        )

    # ---- 2. User strategies ----
    row = await get_user_strategy_by_name(
        session, user_id=user_id, name=strategy_name,
    )
    if row is None:
        raise StrategyNotFoundError(
            f"Strategy {strategy_name!r} not found in built-ins or your "
            f"user_strategies."
        )

    # Compile the source (raises StrategyLoadError on failure — bubbles up)
    cls = load_user_strategy_class(
        source=row["source_code"],
        class_name=row["class_name"],
    )

    return ResolvedStrategy(
        cls=cls,
        name=row["name"],
        description=row.get("description") or "",
        params_schema=row["params_schema"],
        source="user",
        user_strategy_id=row["id"],
    )
