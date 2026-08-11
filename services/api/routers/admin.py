"""Admin console endpoints — platform owner/operator surface.

EVERY endpoint here is gated by `require_admin` (403 for non-admins). Admins are
resolved from `users.role` in the database on each request, so a demotion takes
effect immediately. The first admin is seeded from ADMIN_BOOTSTRAP_EMAILS (see
deps.provision_user_record); from there admins can promote/demote others.

Capabilities:
  GET    /admin/overview                     — platform-wide metrics + config health
  GET    /admin/users                        — every account with activity summary
  GET    /admin/users/{id}                   — one account: profile + their work (support view)
  POST   /admin/users/{id}/role              — promote/demote (member <-> admin)
  POST   /admin/users/{id}/active            — disable / re-enable an account
  DELETE /admin/users/{id}                   — delete an account (cascade)
  DELETE /admin/users/{id}/credentials/{cid} — revoke one of a user's broker keys

Every mutating action writes an `audit_log` row (actor = admin email, before/after
in the payload) so account management and support access are fully traceable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import (
    CurrentUserRecord,
    get_db_session,
    require_admin,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Roles an admin may assign. 'system' is internal and never assignable via the API.
ASSIGNABLE_ROLES = {"member", "admin"}


# ============================================================
# Audit helper
# ============================================================
async def _audit(
    session: AsyncSession,
    *,
    admin: CurrentUserRecord,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
    result: str = "ok",
) -> None:
    """Record an admin action. Actor is the admin's email (falls back to id)."""
    await session.execute(
        text(
            """
            INSERT INTO audit_log
                (user_id, org_id, actor, action, resource_type, resource_id,
                 payload, result)
            VALUES
                (:uid, :org, :actor, :action, :rtype, :rid,
                 CAST(:payload AS JSONB), :result)
            """
        ),
        {
            "uid": admin.id,
            "org": admin.org_id,
            "actor": admin.email or str(admin.id),
            "action": action,
            "rtype": resource_type,
            "rid": resource_id,
            "payload": json.dumps(payload or {}),
            "result": result,
        },
    )


async def _admin_count(session: AsyncSession) -> int:
    r = await session.execute(
        text("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active")
    )
    return int(r.scalar() or 0)


async def _load_user_or_404(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    r = await session.execute(
        text("SELECT id, email, name, role, is_active FROM users WHERE id = :id"),
        {"id": user_id},
    )
    row = r.mappings().first()
    if row is None:
        raise HTTPException(404, "User not found")
    return dict(row)


# ============================================================
# Overview / health
# ============================================================
class AdminOverview(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    admins: int
    users_with_broker_key: int
    active_sessions: int
    live_sessions: int
    config: dict[str, bool]


@router.get("/overview", response_model=AdminOverview)
async def get_overview(
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> AdminOverview:
    async def scalar(sql: str) -> int:
        r = await session.execute(text(sql))
        return int(r.scalar() or 0)

    # Exclude the internal platform/system account from human-facing counts.
    total = await scalar("SELECT COUNT(*) FROM users WHERE role <> 'system'")
    active = await scalar(
        "SELECT COUNT(*) FROM users WHERE role <> 'system' AND is_active"
    )
    admins = await scalar("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    with_key = await scalar(
        "SELECT COUNT(DISTINCT user_id) FROM api_credentials c "
        "JOIN users u ON u.id = c.user_id WHERE u.role <> 'system'"
    )
    active_sessions = await scalar(
        "SELECT COUNT(*) FROM paper_sessions WHERE status IN ('starting','running')"
    )
    live_sessions = await scalar(
        "SELECT COUNT(*) FROM paper_sessions "
        "WHERE status IN ('starting','running') AND mode = 'live'"
    )

    def has(*names: str) -> bool:
        return all(bool(os.environ.get(n)) for n in names)

    config = {
        "ai_copilot": has("ANTHROPIC_API_KEY"),
        "stock_data": has("ALPACA_DATA_KEY_ID", "ALPACA_DATA_SECRET"),
        "crypto_data": has("BINANCEUS_API_KEY", "BINANCEUS_API_SECRET"),
        "key_encryption": has("SETTINGS_ENCRYPTION_KEY"),
        "shared_broker_fallback": os.environ.get(
            "ALLOW_PLATFORM_CREDENTIALS", ""
        ).strip().lower() in {"1", "true", "yes", "on"},
    }

    return AdminOverview(
        total_users=total,
        active_users=active,
        disabled_users=total - active,
        admins=admins,
        users_with_broker_key=with_key,
        active_sessions=active_sessions,
        live_sessions=live_sessions,
        config=config,
    )


# ============================================================
# User list
# ============================================================
class AdminUserRow(BaseModel):
    id: UUID
    email: str | None
    name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_active_at: datetime | None = None
    strategy_count: int
    session_count: int
    broker_key_count: int


@router.get("/users", response_model=list[AdminUserRow])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> list[AdminUserRow]:
    """Every account (excluding the internal system account) with a rollup of
    their strategies, sessions, and connected broker keys."""
    result = await session.execute(
        text(
            """
            SELECT u.id, u.email, u.name, u.role, u.is_active,
                   u.created_at, u.last_active_at,
                   COALESCE(s.cnt, 0) AS strategy_count,
                   COALESCE(p.cnt, 0) AS session_count,
                   COALESCE(c.cnt, 0) AS broker_key_count
              FROM users u
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM user_strategies GROUP BY user_id) s
                     ON s.user_id = u.id
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM paper_sessions GROUP BY user_id) p
                     ON p.user_id = u.id
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM api_credentials GROUP BY user_id) c
                     ON c.user_id = u.id
             WHERE u.role <> 'system'
             ORDER BY u.created_at DESC
            """
        )
    )
    return [AdminUserRow.model_validate(dict(r)) for r in result.mappings()]


# ============================================================
# User detail (support / view-as)
# ============================================================
class AdminUserDetail(BaseModel):
    id: UUID
    email: str | None
    name: str | None
    role: str
    is_active: bool
    strategies: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    broker_keys: list[dict[str, Any]]


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> AdminUserDetail:
    """Read-only support view of one user's work. Logged as an access event."""
    u = await _load_user_or_404(session, user_id)

    strategies = [
        dict(r)
        for r in (
            await session.execute(
                text(
                    "SELECT id, name, asset_class, created_at "
                    "FROM user_strategies WHERE user_id = :id "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                {"id": user_id},
            )
        ).mappings()
    ]
    sessions = [
        dict(r)
        for r in (
            await session.execute(
                text(
                    "SELECT id, strategy_name, mode, status, created_at "
                    "FROM paper_sessions WHERE user_id = :id "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                {"id": user_id},
            )
        ).mappings()
    ]
    # Broker keys: metadata only — NEVER the secret (encrypted_payload excluded).
    broker_keys = [
        dict(r)
        for r in (
            await session.execute(
                text(
                    "SELECT id, service, label, last_four, created_at "
                    "FROM api_credentials WHERE user_id = :id ORDER BY created_at DESC"
                ),
                {"id": user_id},
            )
        ).mappings()
    ]

    await _audit(
        session,
        admin=admin,
        action="admin.user.view",
        resource_type="user",
        resource_id=str(user_id),
    )
    await session.commit()

    return AdminUserDetail(
        id=u["id"],
        email=u["email"],
        name=u["name"],
        role=u["role"],
        is_active=u["is_active"],
        strategies=[_jsonable(s) for s in strategies],
        sessions=[_jsonable(s) for s in sessions],
        broker_keys=[_jsonable(k) for k in broker_keys],
    )


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """UUID/datetime -> str so the row serializes cleanly."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (UUID, datetime)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


# ============================================================
# Role change
# ============================================================
class RoleUpdate(BaseModel):
    role: str = Field(..., description="member | admin")


@router.post("/users/{user_id}/role", response_model=AdminUserRow)
async def set_user_role(
    user_id: UUID,
    body: RoleUpdate,
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> AdminUserRow:
    new_role = body.role.strip().lower()
    if new_role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ASSIGNABLE_ROLES)}")

    target = await _load_user_or_404(session, user_id)
    if target["role"] == "system":
        raise HTTPException(400, "The system account's role cannot be changed.")

    # Guard against locking everyone out: don't demote the last remaining admin.
    if target["role"] == "admin" and new_role != "admin":
        if await _admin_count(session) <= 1:
            raise HTTPException(
                400, "Can't demote the last admin — promote another admin first."
            )

    await session.execute(
        text("UPDATE users SET role = :role, updated_at = NOW() WHERE id = :id"),
        {"role": new_role, "id": user_id},
    )
    await _audit(
        session,
        admin=admin,
        action="admin.user.role",
        resource_type="user",
        resource_id=str(user_id),
        payload={"from": target["role"], "to": new_role},
    )
    await session.commit()
    return await _user_row(session, user_id)


# ============================================================
# Enable / disable
# ============================================================
class ActiveUpdate(BaseModel):
    is_active: bool


@router.post("/users/{user_id}/active", response_model=AdminUserRow)
async def set_user_active(
    user_id: UUID,
    body: ActiveUpdate,
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> AdminUserRow:
    target = await _load_user_or_404(session, user_id)
    if target["role"] == "system":
        raise HTTPException(400, "The system account cannot be disabled.")
    if user_id == admin.id and not body.is_active:
        raise HTTPException(400, "You can't disable your own account.")
    if not body.is_active and target["role"] == "admin" and await _admin_count(session) <= 1:
        raise HTTPException(
            400, "Can't disable the last admin — promote another admin first."
        )

    await session.execute(
        text("UPDATE users SET is_active = :a, updated_at = NOW() WHERE id = :id"),
        {"a": body.is_active, "id": user_id},
    )
    await _audit(
        session,
        admin=admin,
        action="admin.user.active",
        resource_type="user",
        resource_id=str(user_id),
        payload={"is_active": body.is_active},
    )
    await session.commit()
    return await _user_row(session, user_id)


# ============================================================
# Delete account
# ============================================================
@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> None:
    target = await _load_user_or_404(session, user_id)
    if target["role"] == "system":
        raise HTTPException(400, "The system account cannot be deleted.")
    if user_id == admin.id:
        raise HTTPException(400, "You can't delete your own account.")
    if target["role"] == "admin" and await _admin_count(session) <= 1:
        raise HTTPException(400, "Can't delete the last admin.")

    # Non-cascade references must be cleared before the row can be removed.
    await session.execute(
        text("UPDATE audit_log SET user_id = NULL WHERE user_id = :id"),
        {"id": user_id},
    )
    await session.execute(
        text("UPDATE org_settings SET updated_by = NULL WHERE updated_by = :id"),
        {"id": user_id},
    )
    # Everything else (strategies, backtests, sessions, credentials, prefs) is
    # ON DELETE CASCADE, so this removes the user's entire footprint.
    await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await _audit(
        session,
        admin=admin,
        action="admin.user.delete",
        resource_type="user",
        resource_id=str(user_id),
        payload={"email": target["email"]},
    )
    await session.commit()


# ============================================================
# Revoke a user's broker key
# ============================================================
@router.delete("/users/{user_id}/credentials/{credential_id}", status_code=204)
async def revoke_credential(
    user_id: UUID,
    credential_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    admin: CurrentUserRecord = Depends(require_admin),
) -> None:
    result = await session.execute(
        text(
            "DELETE FROM api_credentials WHERE id = :cid AND user_id = :uid"
        ),
        {"cid": credential_id, "uid": user_id},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Credential not found for that user")
    await _audit(
        session,
        admin=admin,
        action="admin.credential.revoke",
        resource_type="api_credential",
        resource_id=str(credential_id),
        payload={"user_id": str(user_id)},
    )
    await session.commit()


async def _user_row(session: AsyncSession, user_id: UUID) -> AdminUserRow:
    """Re-read one user as an AdminUserRow (post-mutation response)."""
    result = await session.execute(
        text(
            """
            SELECT u.id, u.email, u.name, u.role, u.is_active,
                   u.created_at, u.last_active_at,
                   COALESCE(s.cnt, 0) AS strategy_count,
                   COALESCE(p.cnt, 0) AS session_count,
                   COALESCE(c.cnt, 0) AS broker_key_count
              FROM users u
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM user_strategies GROUP BY user_id) s ON s.user_id = u.id
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM paper_sessions GROUP BY user_id) p ON p.user_id = u.id
              LEFT JOIN (SELECT user_id, COUNT(*) cnt FROM api_credentials GROUP BY user_id) c ON c.user_id = u.id
             WHERE u.id = :id
            """
        ),
        {"id": user_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(404, "User not found")
    return AdminUserRow.model_validate(dict(row))
