"""JWT verification for multiple identity providers (Auth0 + Supabase).

The backend never speaks to an IdP to validate tokens. Instead it fetches
each provider's JSON Web Key Set (JWKS) — the public keys the provider uses
to sign tokens — and verifies tokens locally. No network round-trip per
request; the JWKS is cached for an hour.

Two providers are supported, selected per-token by the `iss` claim:

  * **Auth0** — RS256, audience = AUTH0_AUDIENCE, issuer = https://{domain}/.
    Legacy/admin + M2M tokens. Configured via AUTH0_DOMAIN/AUTH0_AUDIENCE.
  * **Supabase** — ES256 (asymmetric signing keys), audience "authenticated",
    issuer = {SUPABASE_URL}/auth/v1. This is what the thebayn frontend sends:
    the user's Supabase session access token, forwarded as a Bearer header.

A token whose issuer matches neither configured provider is rejected (401).
At least one provider must be configured or import fails.

The decoded claims always carry `sub` (the subject). Downstream
(`deps.get_current_user_record`) maps that subject onto the platform `users`
row, lazily provisioning it on first request. Supabase subjects (user UUIDs)
and Auth0 subjects share the `users.auth0_sub` column — it's just an opaque
subject string.

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
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from packages.core.exceptions import ConfigError

log = structlog.get_logger(__name__)


# ============================================================
# Provider configuration (loaded once at import time)
# ============================================================


@dataclass(frozen=True)
class Provider:
    """A trusted token issuer and how to verify its tokens."""

    name: str
    issuer: str
    jwks_url: str
    algorithms: tuple[str, ...]
    audience: str | None  # None = skip audience verification


def _build_providers() -> dict[str, Provider]:
    """Assemble the enabled providers from environment configuration.

    Both providers are optional individually, but at least one must be
    configured. This lets a deployment run Supabase-only, Auth0-only, or
    both during a migration.
    """
    providers: dict[str, Provider] = {}

    auth0_domain = os.environ.get("AUTH0_DOMAIN")
    auth0_audience = os.environ.get("AUTH0_AUDIENCE")
    if auth0_domain and auth0_audience:
        issuer = f"https://{auth0_domain}/"
        providers[issuer] = Provider(
            name="auth0",
            issuer=issuer,
            jwks_url=f"https://{auth0_domain}/.well-known/jwks.json",
            algorithms=("RS256",),
            audience=auth0_audience,
        )

    # Supabase: derive everything from the project URL. The frontend's
    # Supabase project is the default so the integration works out of the box;
    # override with SUPABASE_URL in the environment for other projects.
    supabase_url = os.environ.get(
        "SUPABASE_URL", "https://lkwmpjdojkhysveneubo.supabase.co"
    ).rstrip("/")
    if supabase_url:
        issuer = f"{supabase_url}/auth/v1"
        providers[issuer] = Provider(
            name="supabase",
            issuer=issuer,
            # Supabase signs user tokens with asymmetric keys (ES256) exposed
            # at this JWKS endpoint. No shared secret required.
            jwks_url=f"{supabase_url}/auth/v1/.well-known/jwks.json",
            algorithms=("ES256", "RS256"),
            audience=os.environ.get("SUPABASE_JWT_AUD", "authenticated"),
        )

    if not providers:
        raise ConfigError(
            "No auth provider configured: set AUTH0_DOMAIN/AUTH0_AUDIENCE "
            "and/or SUPABASE_URL"
        )
    return providers


_PROVIDERS = _build_providers()


# ============================================================
# JWKS cache (one-hour TTL, keyed by URL)
# ============================================================


_jwks_cache: dict[str, tuple[dict[str, Any], float]] = {}
_JWKS_CACHE_TTL_S = 3600  # 1 hour


async def _fetch_jwks(url: str) -> dict[str, Any]:
    """Fetch a provider's JWKS, with a one-hour per-URL cache."""
    now = time.monotonic()
    cached = _jwks_cache.get(url)
    if cached is not None and now < cached[1]:
        return cached[0]

    log.info("auth.fetching_jwks", url=url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        jwks = response.json()

    _jwks_cache[url] = (jwks, now + _JWKS_CACHE_TTL_S)
    log.info("auth.jwks_cached", url=url, key_count=len(jwks.get("keys", [])))
    return jwks


# ============================================================
# Token verification
# ============================================================


bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _select_provider(token: str) -> Provider:
    """Pick the provider for a token by its (unverified) issuer claim.

    The issuer is read before signature verification only to route to the
    right keys; the signature, audience, issuer and expiry are all verified
    afterward by ``jwt.decode``.
    """
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError as e:
        raise _unauthorized(f"Malformed token: {e}")

    issuer = claims.get("iss")
    if not issuer:
        raise _unauthorized("Token missing 'iss' claim")

    provider = _PROVIDERS.get(issuer)
    if provider is None:
        raise _unauthorized(f"Untrusted token issuer: {issuer}")
    return provider


def _jwk_for_kid(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    """Return the full JWK matching ``kid`` (works for RSA and EC keys)."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


async def verify_token(token: str) -> dict[str, Any]:
    """Validate a JWT against its issuer's keys and return its claims.

    Raises HTTPException 401 on any failure.
    """
    provider = _select_provider(token)

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise _unauthorized(f"Malformed token header: {e}")

    kid = header.get("kid")
    if not kid:
        raise _unauthorized("Token header missing 'kid'")

    jwks = await _fetch_jwks(provider.jwks_url)
    key = _jwk_for_kid(jwks, kid)
    if key is None:
        # Key may have rotated since we cached; drop cache and retry once.
        _jwks_cache.pop(provider.jwks_url, None)
        jwks = await _fetch_jwks(provider.jwks_url)
        key = _jwk_for_kid(jwks, kid)
    if key is None:
        raise _unauthorized("Token signing key not found in JWKS")

    decode_kwargs: dict[str, Any] = {
        "algorithms": list(provider.algorithms),
        "issuer": provider.issuer,
    }
    if provider.audience is not None:
        decode_kwargs["audience"] = provider.audience
    else:
        decode_kwargs["options"] = {"verify_aud": False}

    try:
        # python-jose accepts the raw JWK dict for both RSA and EC keys.
        return jwt.decode(token, key, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired")
    except jwt.JWTClaimsError as e:
        raise _unauthorized(f"Invalid claims: {e}")
    except JWTError as e:
        raise _unauthorized(f"Token verification failed: {e}")


# ============================================================
# FastAPI dependency
# ============================================================


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency that requires a valid JWT.

    Returns the decoded claims dict and caches it on ``request.state.user``
    so multiple dependencies on one request don't re-verify.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing Authorization header")

    claims = await verify_token(credentials.credentials)
    request.state.user = claims
    return claims
