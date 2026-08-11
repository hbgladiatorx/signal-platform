"""Admin gating: role enforcement and the break-glass bootstrap.

These lock in the two security-critical bits of the admin tier:
  * `require_admin` lets only role=='admin' through (member/system are refused).
  * `_bootstrap_admin_emails` parses the owner allow-list correctly, so the
    owner can always reach the console even on a fresh database.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from services.api.deps import (
    CurrentUserRecord,
    _bootstrap_admin_emails,
    require_admin,
)


def _user(role: str) -> CurrentUserRecord:
    return CurrentUserRecord(
        id=uuid4(), org_id=uuid4(), email="x@example.com", role=role, is_active=True
    )


@pytest.mark.asyncio
async def test_require_admin_allows_admin() -> None:
    admin = _user("admin")
    assert await require_admin(user=admin) is admin


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "system", "", "Admin ", "superuser"])
async def test_require_admin_refuses_non_admin(role: str) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_admin(user=_user(role))
    assert exc.value.status_code == 403


def test_bootstrap_emails_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ADMIN_BOOTSTRAP_EMAILS", " Owner@Example.com , second@x.io ,,"
    )
    emails = _bootstrap_admin_emails()
    assert emails == {"owner@example.com", "second@x.io"}


def test_bootstrap_emails_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_BOOTSTRAP_EMAILS", raising=False)
    assert _bootstrap_admin_emails() == set()
