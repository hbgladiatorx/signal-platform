"""FastAPI dependency injection providers.

These are functions decorated as FastAPI dependencies via `Depends(...)`.
Adding cross-cutting concerns (auth, rate limits, audit logging) means
adding a function here and Depends-ing on it in the route.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.db import session_scope


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for the duration of a single request.

    The session is automatically committed on success or rolled back
    on any exception, via session_scope's context manager.
    """
    async with session_scope() as session:
        yield session
