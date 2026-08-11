"""
Platform (shared) broker credentials.

Lets every user deploy a strategy without first connecting their own broker key:
the platform exposes its OWN broker credentials, sourced from environment
variables, so a user with no personal key falls back to the shared platform
account.

The trading stack keys every broker off an `api_credentials` row (the live
runner decrypts `encrypted_payload` by credential id, and `paper_sessions`
FK-references it). So platform credentials must be real rows — we seed them,
owned by a dedicated system user, with the secrets encrypted at rest exactly
like a user's own key. Secrets live only in the env and the encrypted column;
they are never returned by the API.

Seeding is idempotent and runs on API startup:
  * a service whose env vars are all present is upserted (so rotating an env
    key updates the stored secret on the next restart);
  * a service whose env vars are missing is skipped — e.g. until Alpaca paper
    keys are added, stocks/options simply have no platform credential and the
    deploy path reports that clearly.

Routing (handled by the existing venue→mode map):
  * binanceus → crypto, REAL money  (Binance.US has no sandbox)
  * alpaca    → stocks/options, PAPER (simulated funds)
"""
from __future__ import annotations

import os
from typing import Any, Callable
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.core.encryption import encrypt_json

# Fixed identities for the platform tenant. Stable so seeding is idempotent.
PLATFORM_ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
PLATFORM_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
PLATFORM_USER_SUB = "platform|system"


def platform_fallback_enabled() -> bool:
    """Whether users may trade on the SHARED platform broker keys.

    Default OFF: each user must connect their OWN broker key to place any
    trade. This is the secure, isolated posture — no user ever routes orders
    through the platform's (or another user's) broker account.

    Set ALLOW_PLATFORM_CREDENTIALS=true only for a demo deployment where a
    zero-setup shared *paper* account is acceptable. Note the shared key
    commingles every user's activity on ONE broker account, so it must never
    be enabled with a real-money (Binance.US) key in production.
    """
    return os.environ.get("ALLOW_PLATFORM_CREDENTIALS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _cred_id(service: str) -> UUID:
    """Deterministic, stable credential id per service."""
    return uuid5(PLATFORM_USER_ID, f"platform-credential:{service}")


# service → how to build its encrypted payload from env. A service is available
# only when EVERY listed env var is set and non-empty.
_SPEC: dict[str, dict[str, Any]] = {
    "binanceus": {
        "env": ["BINANCEUS_API_KEY", "BINANCEUS_API_SECRET"],
        "payload": lambda e: {
            "api_key": e["BINANCEUS_API_KEY"],
            "secret_key": e["BINANCEUS_API_SECRET"],
        },
        "last_four_from": "BINANCEUS_API_KEY",
        "label": "Platform Binance.US (shared)",
    },
    "alpaca": {
        "env": ["ALPACA_API_KEY_ID", "ALPACA_SECRET_KEY"],
        "payload": lambda e: {
            "api_key_id": e["ALPACA_API_KEY_ID"],
            "secret_key": e["ALPACA_SECRET_KEY"],
        },
        "last_four_from": "ALPACA_API_KEY_ID",
        "label": "Platform Alpaca paper (shared)",
    },
}


def _env_present(spec: dict[str, Any]) -> dict[str, str] | None:
    vals: dict[str, str] = {}
    for k in spec["env"]:
        v = os.environ.get(k)
        if not v:
            return None
        vals[k] = v
    return vals


async def seed_platform_credentials(engine: AsyncEngine) -> list[str]:
    """Ensure the system tenant and platform credentials exist. Idempotent.

    Returns the list of services that have a live platform credential.
    """
    available: list[str] = []
    async with engine.begin() as conn:
        # System org + user that own the platform credentials.
        await conn.execute(
            text(
                "INSERT INTO organizations (id, name, plan_tier, created_at) "
                "VALUES (:id, 'Platform', 'platform', now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": PLATFORM_ORG_ID},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, org_id, auth0_sub, role, email, name, "
                "created_at, updated_at) VALUES "
                "(:id, :org, :sub, 'system', NULL, 'Platform', now(), now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": PLATFORM_USER_ID, "org": PLATFORM_ORG_ID, "sub": PLATFORM_USER_SUB},
        )

        for service, spec in _SPEC.items():
            env = _env_present(spec)
            if env is None:
                continue  # keys not configured → no platform credential
            payload_builder: Callable[[dict[str, str]], dict[str, Any]] = spec["payload"]
            encrypted = encrypt_json(payload_builder(env))
            last_four = env[spec["last_four_from"]][-4:]
            await conn.execute(
                text(
                    "INSERT INTO api_credentials "
                    "(id, user_id, service, label, encrypted_payload, last_four, created_at) "
                    "VALUES (:id, :uid, :svc, :label, :payload, :last4, now()) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "encrypted_payload = EXCLUDED.encrypted_payload, "
                    "last_four = EXCLUDED.last_four, label = EXCLUDED.label"
                ),
                {
                    "id": _cred_id(service),
                    "uid": PLATFORM_USER_ID,
                    "svc": service,
                    "label": spec["label"],
                    "payload": encrypted,
                    "last4": last_four,
                },
            )
            available.append(service)
    return available


async def list_platform_credentials(conn) -> list[dict[str, Any]]:
    """Platform credentials currently configured. Never exposes secrets."""
    result = await conn.execute(
        text(
            "SELECT id, service, label, last_four FROM api_credentials "
            "WHERE user_id = :uid ORDER BY service"
        ),
        {"uid": PLATFORM_USER_ID},
    )
    return [dict(r) for r in result.mappings().all()]
