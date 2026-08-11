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

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.encryption import encrypt_json
from packages.data.platform_credentials import (
    list_platform_credentials as _list_platform_credentials,
    platform_fallback_enabled,
)
from services.api.auth import get_current_user
from services.api.deps import get_db_session, provision_user_record


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
    # AI copilot — each user connects their own Anthropic key (legacy, key-only).
    "anthropic": {
        "fields": ["api_key"],
        "primary": "api_key",
        "display_name": "Anthropic",
    },
    # AI copilot provider — Anthropic OR any OpenAI-compatible endpoint. The
    # payload carries {provider, api_key, base_url?, model?}; only provider + key
    # are required (base_url/model default from the provider preset).
    "ai_provider": {
        "fields": ["provider", "api_key"],
        "primary": "api_key",
        "display_name": "AI provider",
    },
}


# ============================================================
# User upsert helper
# ============================================================

async def _ensure_user(claims: dict, session: AsyncSession) -> UUID:
    """Resolve (and lazily provision) the caller's platform user UUID.

    Delegates to the shared, email-stable `provision_user_record` so the
    settings endpoints provision users identically to the trading routers —
    one email always maps to one `user_id`, preventing the account
    fragmentation that scatters a person's strategies and credentials across
    duplicate rows after an IdP subject change.
    """
    record = await provision_user_record(claims, session)
    await session.commit()
    return record.id


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
# Free-form preferences (client-owned JSON bag)
# ============================================================

@router.get("/preferences")
async def get_preferences(
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current user's free-form preferences object.

    Mirrors the frontend's former Supabase `user_preferences.prefs` blob.
    Empty object if none set yet.
    """
    user_id = await _ensure_user(claims, session)
    result = await session.execute(
        text("SELECT prefs FROM user_preferences WHERE user_id = :id"),
        {"id": user_id},
    )
    row = result.first()
    return dict(row[0]) if row and row[0] else {}


@router.put("/preferences")
async def update_preferences(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Replace the current user's free-form preferences object.

    The frontend reads the whole bag, mutates it, and writes it back, so this
    is a full replace rather than a merge.
    """
    user_id = await _ensure_user(claims, session)
    await session.execute(
        text(
            """
            INSERT INTO user_preferences (user_id, prefs, updated_at)
            VALUES (:id, CAST(:prefs AS JSONB), NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET prefs = EXCLUDED.prefs, updated_at = NOW()
            """
        ),
        {"id": user_id, "prefs": json.dumps(body)},
    )
    await session.commit()
    return body


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


@router.get("/platform-credentials")
async def list_platform_credentials_endpoint(
    session: AsyncSession = Depends(get_db_session),
    claims: dict = Depends(get_current_user),
) -> list[dict]:
    """Shared platform broker credentials available to every user.

    Empty by default: each user must connect their OWN broker key. Only when
    ALLOW_PLATFORM_CREDENTIALS is enabled (demo mode) does this expose the
    shared keys the deploy path may fall back to. Secrets are never returned —
    only id, service, and a masked last-four.
    """
    await _ensure_user(claims, session)
    if not platform_fallback_enabled():
        return []
    creds = await _list_platform_credentials(session)
    return [
        {
            "id": str(c["id"]),
            "service": c["service"],
            "label": c["label"],
            "last_four": c["last_four"],
            # binanceus = real-money crypto, alpaca = paper stocks/options.
            "mode": "live" if c["service"] in ("binanceus", "alpaca_live") else "paper",
        }
        for c in creds
    ]


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
