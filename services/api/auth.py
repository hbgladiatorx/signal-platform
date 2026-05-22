"""Auth0 JWT verification.

The backend never speaks to Auth0 directly to validate tokens. Instead,
it fetches Auth0's JSON Web Key Set (JWKS) — a set of public keys that
Auth0 uses to sign JWTs — and verifies tokens locally using those keys.

This means: no network round-trip per request, just RSA signature
verification on the token. The JWKS itself is cached for an hour.

A request without a valid JWT gets 401. A request with a valid JWT
sees `request.state.user` populated with the JWT claims.

Usage in routers:
    from fastapi import Depends
    from services.api.auth import get_current_user

    @router.get("/protected")
    async def protected(user: dict = Depends(get_current_user)):
        return {"sub": user["sub"]}
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from packages.core.exceptions import AuthError, ConfigError

log = structlog.get_logger(__name__)


# ============================================================
# Configuration (loaded once at import time)
# ============================================================


def _get_required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Required env var {name} is not set")
    return value


AUTH0_DOMAIN = _get_required("AUTH0_DOMAIN")
AUTH0_AUDIENCE = _get_required("AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]
ISSUER = f"https://{AUTH0_DOMAIN}/"
JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"


# ============================================================
# JWKS cache (one-hour TTL)
# ============================================================


_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expires_at: float = 0.0
_JWKS_CACHE_TTL_S = 3600  # 1 hour


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch Auth0's JWKS, with a one-hour cache.

    JWKS rotates infrequently. Auth0 documents a ~24h rotation cadence,
    so a one-hour cache is conservative.
    """
    global _jwks_cache, _jwks_cache_expires_at

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache

    log.info("auth.fetching_jwks", url=JWKS_URL)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(JWKS_URL)
        response.raise_for_status()
        jwks = response.json()

    _jwks_cache = jwks
    _jwks_cache_expires_at = now + _JWKS_CACHE_TTL_S
    log.info("auth.jwks_cached", key_count=len(jwks.get("keys", [])))
    return jwks


# ============================================================
# Token verification
# ============================================================


bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(token: str) -> dict[str, Any]:
    """Validate a JWT and return its claims.

    Raises HTTPException 401 on any failure.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header missing 'kid'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwks = await _fetch_jwks()
    rsa_key = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
            break

    if rsa_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found in JWKS",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=ALGORITHMS,
            audience=AUTH0_AUDIENCE,
            issuer=ISSUER,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.JWTClaimsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid claims: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ============================================================
# FastAPI dependency
# ============================================================


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency that requires a valid JWT.

    Returns the decoded claims dict. Caches the result on `request.state.user`
    so the same request doesn't re-verify if multiple dependencies use it.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = await verify_token(credentials.credentials)
    request.state.user = claims
    return claims
