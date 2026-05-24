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


async def get_current_user_record(
    claims: dict[str, Any] = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CurrentUserRecord:
    """Look up the platform `users` row for the JWT's `sub` claim.

    Raises 404 if no row exists; this happens for M2M tokens that haven't
    been pre-provisioned.
    """
    auth0_sub = claims.get("sub")
    if not auth0_sub:
        raise HTTPException(401, "Token missing 'sub' claim")
    result = await session.execute(
        text(
            "SELECT id, org_id, email, role FROM users WHERE auth0_sub = :sub"
        ),
        {"sub": auth0_sub},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No user record found for Auth0 subject {auth0_sub!r}. "
                "Use a user-issued token (not M2M) or pre-provision a "
                "users row with this auth0_sub."
            ),
        )
    return CurrentUserRecord(**dict(row))
