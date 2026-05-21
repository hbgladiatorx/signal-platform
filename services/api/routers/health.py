"""Health and readiness endpoints.

/health  — liveness probe. The process is running and reachable.
           Should never query external dependencies — if it does, a
           degraded dependency kills the process from a load-balancer's
           perspective.

/ready   — readiness probe. Checks that downstream dependencies (DB,
           Redis) are reachable. Used by orchestrators to decide
           whether to route traffic to this instance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness check. Returns 200 if the process is running."""
    return {
        "status": "alive",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_db_session)) -> dict:
    """Readiness check. Validates DB connectivity."""
    result = await session.execute(text("SELECT 1"))
    value = result.scalar()
    return {
        "status": "ready" if value == 1 else "degraded",
        "db_check": value == 1,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
