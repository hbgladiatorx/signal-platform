"""Current-user identity endpoint.

GET /me — the canonical "who am I and what can I do?" for the frontend.

Returns the caller's provisioned platform record — id, email, role, and active
status — resolved from the database (not the raw JWT), so the UI can gate
admin-only surfaces on `role`. Provisioning happens here on first sight, exactly
as in every other authenticated route.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from services.api.deps import CurrentUserRecord, get_current_user_record

router = APIRouter(tags=["auth"])


@router.get("/me")
async def get_me(
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> dict[str, object]:
    """Return the authenticated user's platform record.

    Deliberately does NOT echo the full JWT claim set (which can carry
    provider-internal fields) — only the fields the app needs.
    """
    return {
        "id": str(user.id),
        "org_id": str(user.org_id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_admin": user.role == "admin",
    }
