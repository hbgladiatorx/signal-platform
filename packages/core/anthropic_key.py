"""Per-user Anthropic API key resolution.

The AI features (copilot, strategy translation, graph planning, parameter-tweak
advice, backtest narration) run on the SIGNED-IN USER's own Anthropic key, not a
shared platform key. Each user connects their key in Settings; it's encrypted at
rest in `api_credentials` (service='anthropic') exactly like a broker key.

Resolution:
  1. the user's own connected Anthropic key (decrypted), else
  2. the platform ANTHROPIC_API_KEY — ONLY when ALLOW_PLATFORM_AI is enabled
     (default OFF: each user must bring their own).

To avoid threading the key through every call site (some are nested deep in the
copilot tool loop), the request handler resolves it once and stores it in a
request-scoped context variable that each AI call site reads. It FAILS CLOSED:
if no key is in context, the AI feature returns a "connect your key" message
rather than falling back to anything.
"""
from __future__ import annotations

import contextvars
import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.encryption import decrypt_json

# The current request's resolved Anthropic key (None until a handler binds it).
_current_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "anthropic_api_key", default=None
)


def platform_ai_enabled() -> bool:
    """Whether the shared platform ANTHROPIC_API_KEY may be used as a fallback.

    Default OFF: every user connects their own key, and their AI usage bills to
    their own account. Set ALLOW_PLATFORM_AI=true to let users without a key
    fall back to the platform key (the owner then pays for that usage).
    """
    return os.environ.get("ALLOW_PLATFORM_AI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_request_anthropic_key(key: str | None) -> None:
    """Bind the Anthropic key for the current request/task context."""
    _current_key.set(key or None)


def current_anthropic_key() -> str | None:
    """The Anthropic key bound to the current request/task, if any."""
    return _current_key.get()


async def resolve_anthropic_key(
    session: AsyncSession, user_id: UUID
) -> str | None:
    """Resolve the Anthropic key for a user: their own key, else the platform
    key only when ALLOW_PLATFORM_AI is enabled. Never raises."""
    row = (
        await session.execute(
            text(
                "SELECT encrypted_payload FROM api_credentials "
                "WHERE user_id = :uid AND service = 'anthropic' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is not None:
        try:
            payload = decrypt_json(row[0])
        except Exception:  # noqa: BLE001 — a bad token must never 500 the AI path
            payload = {}
        key = (payload.get("api_key") or "").strip()
        if key:
            return key

    if platform_ai_enabled():
        return (os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None
    return None


async def bind_request_anthropic_key(
    session: AsyncSession, user_id: UUID
) -> str | None:
    """Resolve the user's key and bind it to the request context. Returns it."""
    key = await resolve_anthropic_key(session, user_id)
    set_request_anthropic_key(key)
    return key
