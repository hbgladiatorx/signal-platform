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


async def provision_user_record(
    claims: dict[str, Any],
    session: AsyncSession,
) -> CurrentUserRecord:
    """Resolve (and lazily provision) the platform `users` row for a JWT's
    claims, using email-stable identity.

    Shared by `get_current_user_record` (the trading routers) and the settings
    router's `_ensure_user`, so every entry point provisions users identically
    and one email always maps to one `user_id` — no matter which endpoint a
    freshly-signed-in user hits first. Does not commit; the caller's session
    context is responsible for that.
    """
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(401, "Token missing 'sub' claim")
    email = claims.get("email")
    name = _claim_name(claims)

    # Email-stable identity. Matching by subject is the primary, unchanged path.
    # But if this subject has NO row yet and its email already owns an account
    # (e.g. the same person after an Auth0 -> Supabase migration, where the token
    # `sub` changed), adopt the existing account onto the new subject instead of
    # silently creating a duplicate. This keeps one email = one user_id and
    # prevents the account fragmentation that scatters strategies/sessions.
    if email:
        has_sub = await session.execute(
            text("SELECT 1 FROM users WHERE auth0_sub = :sub"), {"sub": sub}
        )
        if has_sub.first() is None:
            adopted = await session.execute(
                text(
                    """
                    UPDATE users
                       SET auth0_sub = :sub,
                           name = COALESCE(:name, name),
                           updated_at = NOW()
                     WHERE id = (
                         SELECT id FROM users
                          WHERE email = :email
                          ORDER BY created_at
                          LIMIT 1
                     )
                    RETURNING id, org_id, email, role
                    """
                ),
                {"sub": sub, "email": email, "name": name},
            )
            arow = adopted.mappings().first()
            if arow is not None:
                return CurrentUserRecord(**dict(arow))

    result = await session.execute(
        text(
            """
            INSERT INTO users (auth0_sub, email, name)
            VALUES (:sub, :email, :name)
            ON CONFLICT (auth0_sub) DO UPDATE SET updated_at = NOW()
            RETURNING id, org_id, email, role
            """
        ),
        {"sub": sub, "email": email, "name": name},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to provision user")
    return CurrentUserRecord(**dict(row))


async def get_current_user_record(
    claims: dict[str, Any] = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CurrentUserRecord:
    """FastAPI dependency: the platform `users` row for the caller's JWT.

    Thin wrapper over `provision_user_record` so routers can `Depends(...)` on
    it directly. The subject is opaque — an Auth0 sub or a Supabase user UUID.
    M2M tokens without a `sub` are rejected (401).
    """
    return await provision_user_record(claims, session)
