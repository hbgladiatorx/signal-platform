"""User identity endpoint.

GET /me — returns the claims from the current request's JWT.

This is the canonical way for the frontend to ask "who am I and what
can I see?" — and for us to verify the auth flow works end-to-end.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from services.api.auth import get_current_user

router = APIRouter(tags=["auth"])


@router.get("/me")
async def get_me(claims: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the JWT claims of the authenticated principal.

    For user tokens, this includes 'sub' (the Auth0 user ID),
    'email', and other profile claims (if the requesting application
    requested scopes that include them).

    For machine-to-machine tokens, only 'sub' (the M2M client name)
    and standard JWT claims (iss, aud, exp, etc.) are present.
    """
    return {
        "sub": claims.get("sub"),
        "iss": claims.get("iss"),
        "aud": claims.get("aud"),
        "scope": claims.get("scope"),
        "exp": claims.get("exp"),
        "iat": claims.get("iat"),
        # Full claims for debugging — remove from response in production multi-user
        "claims": claims,
    }
