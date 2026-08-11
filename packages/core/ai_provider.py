"""Per-user AI provider configuration.

The AI features run on the SIGNED-IN USER's own provider + key. A user picks a
provider (Anthropic, or any OpenAI-compatible endpoint — OpenAI, DeepSeek, Groq,
OpenRouter, or a custom base URL), a model, and an API key. The config is stored
encrypted in `api_credentials` (service='ai_provider') exactly like a broker key.

Resolution order (see resolve_ai_provider):
  1. the user's own 'ai_provider' credential,
  2. a legacy 'anthropic' credential (key-only) — treated as provider=anthropic,
  3. the platform ANTHROPIC_API_KEY, ONLY when ALLOW_PLATFORM_AI is enabled.

Like the broker keys, it FAILS CLOSED: no config -> the AI features tell the user
to connect a provider rather than falling back to anything.
"""
from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.encryption import decrypt_json


@dataclass(frozen=True)
class ProviderPreset:
    """A known provider: how to reach it and a sensible default model."""

    key: str
    label: str
    kind: str  # "anthropic" (native SDK) or "openai" (OpenAI-compatible)
    base_url: str | None  # None for the Anthropic native SDK
    default_model: str
    requires_model: bool  # True when the user must choose a model (no safe default)


# The Anthropic default model is owned by the copilot prompt module; import lazily
# to avoid a cycle and keep a single source of truth.
def _anthropic_default_model() -> str:
    try:
        from packages.copilot.prompt import COPILOT_MODEL

        return COPILOT_MODEL
    except Exception:  # noqa: BLE001
        return "claude-sonnet-4-5"


PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        "anthropic", "Anthropic (Claude)", "anthropic", None,
        _anthropic_default_model(), requires_model=False,
    ),
    "openai": ProviderPreset(
        "openai", "OpenAI", "openai", "https://api.openai.com/v1",
        "gpt-4o-mini", requires_model=False,
    ),
    "deepseek": ProviderPreset(
        "deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1",
        "deepseek-chat", requires_model=False,
    ),
    "groq": ProviderPreset(
        "groq", "Groq", "openai", "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile", requires_model=False,
    ),
    "openrouter": ProviderPreset(
        "openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1",
        "openai/gpt-4o-mini", requires_model=False,
    ),
    "custom": ProviderPreset(
        "custom", "Custom (OpenAI-compatible)", "openai", None,
        "", requires_model=True,
    ),
}


@dataclass(frozen=True)
class AIProviderConfig:
    """A fully-resolved AI provider ready to make a call."""

    provider: str          # preset key: anthropic|openai|deepseek|groq|openrouter|custom
    kind: str              # "anthropic" | "openai"
    base_url: str | None
    model: str             # the model to use (already defaulted)
    api_key: str

    @property
    def is_openai(self) -> bool:
        return self.kind == "openai"


_current: contextvars.ContextVar[AIProviderConfig | None] = contextvars.ContextVar(
    "ai_provider_config", default=None
)


def platform_ai_enabled() -> bool:
    """Whether the shared platform ANTHROPIC_API_KEY may be used as a fallback.

    Default OFF — every user connects their own provider/key.
    """
    return os.environ.get("ALLOW_PLATFORM_AI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_request_ai_config(cfg: AIProviderConfig | None) -> None:
    _current.set(cfg)


def current_ai_config() -> AIProviderConfig | None:
    return _current.get()


def build_config(
    *, provider: str, api_key: str, base_url: str | None = None, model: str | None = None
) -> AIProviderConfig | None:
    """Assemble a config from stored fields + the provider preset. Returns None
    if the essentials (a key, and a usable base_url/model) can't be satisfied."""
    key = (api_key or "").strip()
    if not key:
        return None
    preset = PRESETS.get(provider) or PRESETS["custom"]
    resolved_base = (base_url or "").strip() or preset.base_url
    resolved_model = (model or "").strip()
    if preset.kind == "openai":
        # OpenAI-compatible calls need both a base_url and a concrete model.
        resolved_model = resolved_model or preset.default_model
        if not resolved_base or not resolved_model:
            return None
    # For the Anthropic native SDK an empty model means "use the caller's
    # per-feature default" (copilot/narrate/etc. each keep their own model).
    return AIProviderConfig(
        provider=preset.key,
        kind=preset.kind,
        base_url=resolved_base,
        model=resolved_model,
        api_key=key,
    )


async def resolve_ai_provider(
    session: AsyncSession, user_id: UUID
) -> AIProviderConfig | None:
    """Resolve the user's AI provider config. Never raises."""
    # 1) The user's explicit AI-provider credential.
    row = (
        await session.execute(
            text(
                "SELECT encrypted_payload FROM api_credentials "
                "WHERE user_id = :uid AND service = 'ai_provider' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is not None:
        try:
            p = decrypt_json(row[0])
        except Exception:  # noqa: BLE001
            p = {}
        cfg = build_config(
            provider=p.get("provider") or "anthropic",
            api_key=p.get("api_key") or "",
            base_url=p.get("base_url"),
            model=p.get("model"),
        )
        if cfg is not None:
            return cfg

    # 2) Legacy Anthropic key-only credential (from the first per-user AI build).
    legacy = (
        await session.execute(
            text(
                "SELECT encrypted_payload FROM api_credentials "
                "WHERE user_id = :uid AND service = 'anthropic' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": user_id},
        )
    ).first()
    if legacy is not None:
        try:
            p = decrypt_json(legacy[0])
        except Exception:  # noqa: BLE001
            p = {}
        cfg = build_config(provider="anthropic", api_key=p.get("api_key") or "")
        if cfg is not None:
            return cfg

    # 3) Platform fallback — only when explicitly enabled.
    if platform_ai_enabled():
        cfg = build_config(
            provider="anthropic", api_key=os.environ.get("ANTHROPIC_API_KEY") or ""
        )
        if cfg is not None:
            return cfg
    return None


async def bind_request_ai_config(
    session: AsyncSession, user_id: UUID
) -> AIProviderConfig | None:
    """Resolve the user's provider config and bind it to the request context."""
    cfg = await resolve_ai_provider(session, user_id)
    set_request_ai_config(cfg)
    return cfg
