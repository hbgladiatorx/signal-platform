"""Per-user Anthropic key: platform-fallback flag + request-scoped binding.

Locks in the secure default (each user brings their own key; no shared fallback
unless ALLOW_PLATFORM_AI is explicitly enabled) and the context-var transport
that carries the resolved key to every AI call site.
"""
from __future__ import annotations

import pytest

from packages.core.anthropic_key import (
    current_anthropic_key,
    platform_ai_enabled,
    set_request_anthropic_key,
)


def test_platform_ai_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PLATFORM_AI", raising=False)
    assert platform_ai_enabled() is False


@pytest.mark.parametrize("val", ["true", "TRUE", "1", "yes", "on"])
def test_platform_ai_enabled_truthy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("ALLOW_PLATFORM_AI", val)
    assert platform_ai_enabled() is True


@pytest.mark.parametrize("val", ["", "false", "0", "no", "off"])
def test_platform_ai_disabled_falsy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("ALLOW_PLATFORM_AI", val)
    assert platform_ai_enabled() is False


def test_request_key_binding_roundtrip() -> None:
    set_request_anthropic_key("sk-ant-abc")
    assert current_anthropic_key() == "sk-ant-abc"
    # Empty binds to None (fails closed rather than passing an empty key).
    set_request_anthropic_key("")
    assert current_anthropic_key() is None
