"""
Data-access layer for user_strategies.

Functions are async and take a SQLAlchemy AsyncSession. Calls do not
commit — the caller is responsible for transaction management via
session_scope.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ============================================================
# Create
# ============================================================

async def create_user_strategy(
    session: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    name: str,
    description: Optional[str],
    nl_description: Optional[str],
    class_name: str,
    source_code: str,
    params_schema: dict[str, Any],
) -> UUID:
    """Insert a new user_strategy row. Returns the new id."""
    result = await session.execute(
        text(
            """
            INSERT INTO user_strategies (
                user_id, org_id, name, description, nl_description,
                class_name, source_code, params_schema
            )
            VALUES (
                :user_id, :org_id, :name, :description, :nl_description,
                :class_name, :source_code, CAST(:params_schema AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "org_id": org_id,
            "name": name,
            "description": description,
            "nl_description": nl_description,
            "class_name": class_name,
            "source_code": source_code,
            "params_schema": _to_json(params_schema),
        },
    )
    row = result.first()
    assert row is not None
    return row[0]


# ============================================================
# Read
# ============================================================

async def get_user_strategy(
    session: AsyncSession,
    *,
    strategy_id: UUID,
    user_id: UUID,
) -> Optional[dict[str, Any]]:
    """Fetch a single strategy by id, scoped to its owning user."""
    result = await session.execute(
        text(
            """
            SELECT
                id, user_id, org_id, name, description, nl_description,
                class_name, source_code, params_schema, is_active,
                created_at, updated_at
            FROM user_strategies
            WHERE id = :id AND user_id = :user_id
            """
        ),
        {"id": strategy_id, "user_id": user_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_strategy_by_name(
    session: AsyncSession,
    *,
    user_id: UUID,
    name: str,
) -> Optional[dict[str, Any]]:
    """Fetch by user + name (active only). For backtest worker lookup."""
    result = await session.execute(
        text(
            """
            SELECT
                id, user_id, org_id, name, description, nl_description,
                class_name, source_code, params_schema, is_active,
                created_at, updated_at
            FROM user_strategies
            WHERE user_id = :user_id AND name = :name AND is_active = TRUE
            """
        ),
        {"user_id": user_id, "name": name},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_user_strategies_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    include_inactive: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List a user's strategies, newest first. Excludes soft-deleted by default."""
    if include_inactive:
        where_clause = "WHERE user_id = :user_id"
    else:
        where_clause = "WHERE user_id = :user_id AND is_active = TRUE"

    result = await session.execute(
        text(
            f"""
            SELECT
                id, user_id, org_id, name, description, nl_description,
                class_name, params_schema, is_active,
                created_at, updated_at
            FROM user_strategies
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return [dict(r) for r in result.mappings().all()]


# ============================================================
# Update
# ============================================================

async def update_user_strategy(
    session: AsyncSession,
    *,
    strategy_id: UUID,
    user_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    nl_description: Optional[str] = None,
    class_name: Optional[str] = None,
    source_code: Optional[str] = None,
    params_schema: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Update mutable fields on a user_strategy.

    Returns True if a row was updated, False if not found / not owned.
    Only fields whose value is not None are touched.
    """
    sets: list[str] = []
    params: dict[str, Any] = {
        "id": strategy_id,
        "user_id": user_id,
        "now": datetime.utcnow(),
    }
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
    if description is not None:
        sets.append("description = :description")
        params["description"] = description
    if nl_description is not None:
        sets.append("nl_description = :nl_description")
        params["nl_description"] = nl_description
    if class_name is not None:
        sets.append("class_name = :class_name")
        params["class_name"] = class_name
    if source_code is not None:
        sets.append("source_code = :source_code")
        params["source_code"] = source_code
    if params_schema is not None:
        sets.append("params_schema = CAST(:params_schema AS JSONB)")
        params["params_schema"] = _to_json(params_schema)

    if not sets:
        # Nothing to update — treat as a no-op success
        return True

    sets.append("updated_at = :now")
    set_clause = ", ".join(sets)

    result = await session.execute(
        text(
            f"""
            UPDATE user_strategies
            SET {set_clause}
            WHERE id = :id AND user_id = :user_id
            """
        ),
        params,
    )
    return result.rowcount > 0


async def soft_delete_user_strategy(
    session: AsyncSession,
    *,
    strategy_id: UUID,
    user_id: UUID,
) -> bool:
    """Set is_active = FALSE. Returns True if a row was updated."""
    result = await session.execute(
        text(
            """
            UPDATE user_strategies
            SET is_active = FALSE, updated_at = now()
            WHERE id = :id AND user_id = :user_id AND is_active = TRUE
            """
        ),
        {"id": strategy_id, "user_id": user_id},
    )
    return result.rowcount > 0


# ============================================================
# Helpers
# ============================================================

def _to_json(obj: Any) -> str:
    """Serialize a Python dict to a JSON string for JSONB casting."""
    import json
    return json.dumps(obj)
