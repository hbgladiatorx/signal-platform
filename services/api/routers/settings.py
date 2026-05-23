"""Settings endpoints — profile and encrypted API credentials.

All endpoints are JWT-protected via `get_current_user`. On first call to
any endpoint, the user's Auth0 sub is upserted into `users`. This is
lazy provisioning: we don't need to write a sync job; identity creation
happens at first request.

Endpoints:
  GET    /settings/profile                — current user's profile + prefs
  PUT    /settings/profile                — update name/timezone/theme/notifications
  POST   /settings/profile/sync           — sync email/name from JWT-fronted IdP data

  GET    /settings/api-keys               — list this user's API credentials (summary, never the secret)
  POST   /settings/api-keys               — create a new credential (encrypted at rest)
  DELETE /settings/api-keys/{id}          — delete a credential
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.encryption import encrypt_json
from services.api.auth import get_current_user
from services.api.deps import get_db_session


router = APIRouter(prefix="/settings", tags=["settings"])


# ============================================================
# Service schema (frontend mirrors this)
# ============================================================

# Maps service identifier to required field names and the field treated
# as the "primary" key for last-4 display. Phase 1 ships Binance.US.
# Adding a service is a 1-line change here + a 1-line addition in the
# frontend SERVICE_SCHEMAS object.
SERVICE_FIELDS: dict[str, dict[str, Any]] = {
    "binanceus": {
        "fields": ["api_key", "secret_key"],
        "primary": "api_key",
        "display_name": "Binance.US",
    },
    "alpaca": {
        "fields": ["api_key_id", "secret_key"],
        "primary": "api_key_id",
        "display_name": "Alpaca",
    },
}


# ============================================================
# User upsert helper
# ============================================================

async def _ensure_user(claims: dict, session: AsyncSession) -> UUID:
    """
    Upsert the user keyed by Auth0 sub. Returns the platform user UUID.
    Pure SQL upsert with RETURNING for atomicity.
    """
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing 'sub' claim",
        )

    result = await session.execute(
        text(
            """
            INSERT INTO users (auth0_sub, email, name)
            VALUES (:sub, :email, :name)
            ON CONFLICT (auth0_sub) DO UPDATE
                SET updated_at = NOW()
            RETURNING id
            """
        ),
        {
            "sub": sub,
            "email": claims.get("email"),
            "name": claims.get("name"),
        },
    )
    await session.commit()
    row = result.first()
    if row is None:
        # Should not happen with the ON CONFLICT DO UPDATE clause; defensive.
        raise HTTPException(status_code=500, detail="Failed to upsert user")
    return row.id


# ============================================================
# Profile models
# ============================================================

class ProfileResponse(BaseModel):
    user_id: UUID
    auth0_sub: str
    email: str | None
    name: str | None
    timezone: str
    theme: str
    notifications_enabled: bool
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    notifications_enabled: bool | None = None


class ProfileSync(BaseModel):
    """Frontend-supplied user data from the Auth0 ID token (not the access token)."""

    email: str | None = Field(default=None, max_length=254)
    name: str | None = Field(default=None, max_length=120)


async def _load_profile(user_id: UUID, session: AsyncSession) -> ProfileResponse:
    result = await session.execute(
        text(
            """
            SELECT u.id AS user_id, u.auth0_sub, u.email, u.name, u.created_at,
                   COALESCE(p.timezone, 'UTC') AS timezone,
                   COALESCE(p.theme, 'light') AS theme,
                   COALESCE(p.notifications_enabled, FALSE) AS notifications_enabled
            FROM users u
            LEFT JOIN user_preferences p ON p.user_id = u.id
            WHERE u.id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=500, detail="User row vanished after upsert")
    return ProfileResponse.model_validate(dict(row))


# ============================================================
# Profile endpoints
# ============================================================

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> ProfileResponse:
    user_id = await _ensure_user(claims, session)
    return await _load_profile(user_id, session)


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> ProfileResponse:
    user_id = await _ensure_user(claims, session)

    if body.name is not None:
        await session.execute(
            text(
                "UPDATE users SET name = :name, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"name": body.name, "id": user_id},
        )

    pref_updates: dict[str, Any] = {}
    if body.timezone is not None:
        pref_updates["timezone"] = body.timezone
    if body.theme is not None:
        pref_updates["theme"] = body.theme
    if body.notifications_enabled is not None:
        pref_updates["notifications_enabled"] = body.notifications_enabled

    if pref_updates:
        cols = list(pref_updates.keys())
        col_list = ", ".join(cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        await session.execute(
            text(
                f"""
                INSERT INTO user_preferences (user_id, {col_list}, updated_at)
                VALUES (:user_id, {placeholders}, NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET {update_clause}, updated_at = NOW()
                """
            ),
            {"user_id": user_id, **pref_updates},
        )

    await session.commit()
    return await _load_profile(user_id, session)


@router.post("/profile/sync", response_model=ProfileResponse)
async def sync_profile_from_idp(
    body: ProfileSync,
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> ProfileResponse:
    """
    Populate email/name from the IdP (Auth0 ID token), if currently null.
    Frontend calls this on first login. Existing values are not overwritten.
    """
    user_id = await _ensure_user(claims, session)

    set_clauses: list[str] = []
    params: dict[str, Any] = {"id": user_id}
    if body.email:
        set_clauses.append("email = COALESCE(email, :email)")
        params["email"] = body.email
    if body.name:
        set_clauses.append("name = COALESCE(name, :name)")
        params["name"] = body.name

    if set_clauses:
        await session.execute(
            text(
                f"UPDATE users SET {', '.join(set_clauses)}, updated_at = NOW() "
                "WHERE id = :id"
            ),
            params,
        )
        await session.commit()

    return await _load_profile(user_id, session)


# ============================================================
# API credential models
# ============================================================

class APICredentialSummary(BaseModel):
    """Safe-to-display credential metadata. Never includes the secret."""

    id: UUID
    service: str
    label: str
    last_four: str | None
    created_at: datetime
    last_used_at: datetime | None


class APICredentialCreate(BaseModel):
    service: str = Field(..., max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, str] = Field(..., description="Service-specific keys")


# ============================================================
# API credential endpoints
# ============================================================

@router.get("/api-keys", response_model=list[APICredentialSummary])
async def list_api_keys(
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> list[APICredentialSummary]:
    user_id = await _ensure_user(claims, session)
    result = await session.execute(
        text(
            """
            SELECT id, service, label, last_four, created_at, last_used_at
            FROM api_credentials
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            """
        ),
        {"user_id": user_id},
    )
    return [APICredentialSummary.model_validate(dict(r)) for r in result.mappings()]


@router.post("/api-keys", response_model=APICredentialSummary, status_code=201)
async def create_api_key(
    body: APICredentialCreate,
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> APICredentialSummary:
    user_id = await _ensure_user(claims, session)

    # Validate service identifier
    schema = SERVICE_FIELDS.get(body.service)
    if schema is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported service '{body.service}'. "
                f"Allowed: {sorted(SERVICE_FIELDS.keys())}"
            ),
        )

    # Validate every required field is present and non-empty
    missing = [
        f for f in schema["fields"]
        if not body.payload.get(f) or not str(body.payload[f]).strip()
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing or empty fields for {body.service}: {missing}",
        )

    # Strip whitespace defensively
    cleaned = {k: str(v).strip() for k, v in body.payload.items()}

    primary_field = schema["primary"]
    primary_value = cleaned.get(primary_field, "")
    last_four = primary_value[-4:] if len(primary_value) >= 4 else None

    encrypted = encrypt_json(cleaned)

    try:
        result = await session.execute(
            text(
                """
                INSERT INTO api_credentials
                    (user_id, service, label, encrypted_payload, last_four)
                VALUES
                    (:user_id, :service, :label, :encrypted, :last_four)
                RETURNING id, service, label, last_four, created_at, last_used_at
                """
            ),
            {
                "user_id": user_id,
                "service": body.service,
                "label": body.label,
                "encrypted": encrypted,
                "last_four": last_four,
            },
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Most common failure: unique constraint violation on (user_id, service, label)
        if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(
                status_code=409,
                detail=f"A credential with label '{body.label}' "
                       f"for {body.service} already exists",
            )
        raise

    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="Insert returned no row")
    return APICredentialSummary.model_validate(dict(row))


@router.delete("/api-keys/{credential_id}", status_code=204)
async def delete_api_key(
    credential_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> None:
    user_id = await _ensure_user(claims, session)

    result = await session.execute(
        text(
            "DELETE FROM api_credentials "
            "WHERE id = :id AND user_id = :user_id"
        ),
        {"id": credential_id, "user_id": user_id},
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Credential not found")
