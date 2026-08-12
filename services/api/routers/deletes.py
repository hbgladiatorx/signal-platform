"""Deletion endpoints for backtests and walk-forwards.

These live in a dedicated, self-contained module so the capability could be
added without rewriting the larger `backtests`/`walkforwards` routers. Both
endpoints are owner-scoped: a user can only delete their own runs, and a
missing or someone-else's row returns 404 (so existence is never revealed).

  DELETE /backtests/{id}      — removes the run; its backtest_trades and
                                backtest_equity_points rows are removed via
                                their ON DELETE CASCADE foreign keys.
  DELETE /walkforwards/{id}   — removes the run (window results are stored
                                inline on the row, so one DELETE suffices).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from packages.data.db import get_engine
from services.api.deps import get_current_user_record, get_db_session

router = APIRouter(tags=["deletions"])


@router.delete("/backtests/{backtest_id}", status_code=204)
async def delete_backtest_endpoint(
    backtest_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: Any = Depends(get_current_user_record),
) -> None:
    """Delete a backtest you own (cascades to its trades and equity points)."""
    row = (
        await session.execute(
            text("SELECT user_id FROM backtests WHERE id = :id"),
            {"id": backtest_id},
        )
    ).first()
    if row is None or str(row[0]) != str(user.id):
        # 404 (not 403) so we don't reveal another user's backtest exists.
        raise HTTPException(status_code=404, detail="Backtest not found")
    await session.execute(
        text("DELETE FROM backtests WHERE id = :id AND user_id = :uid"),
        {"id": backtest_id, "uid": user.id},
    )
    await session.commit()


@router.delete("/paper-sessions/{session_id}", status_code=204)
async def delete_paper_session_endpoint(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: Any = Depends(get_current_user_record),
) -> None:
    """Delete a paper/live session you own. It must be stopped first — deleting a
    running session's row out from under the worker is what creates ghost
    sessions. Cascades to its orders, fills, positions and equity points."""
    row = (
        await session.execute(
            text("SELECT user_id, status FROM paper_sessions WHERE id = :id"),
            {"id": session_id},
        )
    ).first()
    if row is None or str(row[0]) != str(user.id):
        # 404 (not 403) so we don't reveal another user's session exists.
        raise HTTPException(status_code=404, detail="Session not found")
    if str(row[1]) in {"running", "starting", "stopping"}:
        raise HTTPException(
            status_code=409, detail="Stop the session before deleting it."
        )
    await session.execute(
        text("DELETE FROM paper_sessions WHERE id = :id AND user_id = :uid"),
        {"id": session_id, "uid": user.id},
    )
    await session.commit()


@router.delete("/walkforwards/{walkforward_id}", status_code=204)
async def delete_walkforward_endpoint(
    walkforward_id: UUID,
    user: Any = Depends(get_current_user_record),
) -> None:
    """Delete a walk-forward job you own."""
    engine: AsyncEngine = get_engine()
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT user_id FROM walkforwards WHERE id = :id"),
                {"id": str(walkforward_id)},
            )
        ).first()
        if row is None or str(row[0]) != str(user.id):
            raise HTTPException(status_code=404, detail="Walkforward not found")
        await conn.execute(
            text("DELETE FROM walkforwards WHERE id = :id AND user_id = :uid"),
            {"id": str(walkforward_id), "uid": str(user.id)},
        )
