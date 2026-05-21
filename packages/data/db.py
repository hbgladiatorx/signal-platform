"""Async database connection and session management.

A single engine/sessionmaker pair is created lazily on first use and
reused for the lifetime of the process. The `session_scope` context
manager is the public entry point for database operations.

Usage:
    async with session_scope() as session:
        result = await session.execute(text("SELECT 1"))

The DATABASE_URL is read from the environment and rewritten to use the
asyncpg driver. Other drivers will not work with the async stack.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from packages.core.exceptions import ConfigError


def _get_database_url() -> str:
    """Return DATABASE_URL rewritten to use the asyncpg driver."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL is not set in the environment")

    # SQLAlchemy needs the async driver explicitly named in the URL.
    # Standard 'postgresql://' is the sync default; rewrite to '+asyncpg'.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first call."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            _get_database_url(),
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory."""
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager that yields an AsyncSession.

    Commits on successful exit; rolls back if an exception is raised
    inside the block. Always closes the session.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose of the engine. Used at process shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
