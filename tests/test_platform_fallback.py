"""Security posture: shared platform broker credentials are OFF by default.

The product rule is "each user connects their own broker key and only ever
trades on their own account". That is enforced by `platform_fallback_enabled()`
gating every path that would otherwise let a user route orders through the
shared platform (system-owned) credential. These tests lock in the default and
the opt-in switch so a future edit can't silently re-open the shared account.
"""
from __future__ import annotations

import pytest

from packages.data.platform_credentials import platform_fallback_enabled


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PLATFORM_CREDENTIALS", raising=False)
    assert platform_fallback_enabled() is False


@pytest.mark.parametrize("val", ["true", "True", "1", "yes", "on", "  ON  "])
def test_enabled_for_truthy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("ALLOW_PLATFORM_CREDENTIALS", val)
    assert platform_fallback_enabled() is True


@pytest.mark.parametrize("val", ["", "false", "0", "no", "off", "disabled", "maybe"])
def test_disabled_for_falsy_values(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("ALLOW_PLATFORM_CREDENTIALS", val)
    assert platform_fallback_enabled() is False
