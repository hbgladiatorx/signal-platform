"""FastAPI dependency injection providers.

These are functions decorated as FastAPI dependencies via `Depends(...)`.
Adding cross-cutting concerns (auth, rate limits, audit logging) means
adding a function here and Depends-ing on it in the route.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.db import session_scope
from services.api.auth import get_current_user


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for the duration of a single request.

    The session is automatically committed on success or rolled back
    on any exception, via session_scope's context manager.
    """
    async with session_scope() as session:
        yield session


# ============================================================
# Current-user record
# ============================================================
#
# NOTE: A copy of this helper exists inline in
# `services/api/routers/backtests.py` from Step 23 — both are
# functionally identical. The duplicate should be removed in a
# cleanup pass (cleanup carryover #N).
# ============================================================

class CurrentUserRecord(BaseModel):
    id: UUID
    org_id: UUID
    email: str | None = None
    role: str


def _claim_name(claims: dict[str, Any]) -> str | None:
    """Best-effort display name across IdPs.

    Auth0 puts it in `name`; Supabase nests it under `user_metadata`.
    """
    if claims.get("name"):
        return claims["name"]
    meta = claims.get("user_metadata") or {}
    return meta.get("name") or meta.get("full_name")


async def get_current_user_record(
    claims: dict[str, Any] = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CurrentUserRecord:
    """Resolve the platform `users` row for the JWT's `sub`, provisioning it
    on first sight.

    The subject is opaque — an Auth0 sub or a Supabase user UUID — and is
    stored in `users.auth0_sub`. Lazy provisioning means a freshly signed-up
    Supabase user gets a platform row on their very first authenticated
    request, with no separate sync job. M2M tokens without a `sub` are
    rejected (401).
    """
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(401, "Token missing 'sub' claim")
    result = await session.execute(
        text(
            """
            INSERT INTO users (auth0_sub, email, name)
            VALUES (:sub, :email, :name)
            ON CONFLICT (auth0_sub) DO UPDATE SET updated_at = NOW()
            RETURNING id, org_id, email, role
            """
        ),
        {
            "sub": sub,
            "email": claims.get("email"),
            "name": _claim_name(claims),
        },
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to provision user")
    return CurrentUserRecord(**dict(row))
