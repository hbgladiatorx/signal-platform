"""Walk-forward analysis API endpoints.

POST /walkforwards         create + enqueue
GET  /walkforwards         list user's walk-forwards
GET  /walkforwards/{id}    full details including per-window results
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.backtest.walkforward_persistence import (
    create_walkforward,
    list_walkforwards_for_user,
    load_walkforward,
)
from packages.data.db import get_engine
from packages.data.messagebus import QUEUE_WALKFORWARD_JOBS

# Re-using existing auth helper from elsewhere in the API
from services.api.deps import get_current_user_record  # type: ignore


router = APIRouter(prefix="/walkforwards", tags=["walkforwards"])


# ============================================================
# Schemas
# ============================================================
class CreateWalkforwardRequest(BaseModel):
    """User-facing payload for POST /walkforwards."""
    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field(..., min_length=1, max_length=200)
    symbols: list[str] = Field(..., min_length=1)
    bar_resolution: str = Field(..., pattern=r"^(1m|5m|15m|1h|4h|1d)$")
    starting_cash: Decimal = Field(default=Decimal("10000"), gt=0)
    fee_rate_bps: int = Field(default=10, ge=0, le=1000)
    slippage_bps: int = Field(default=5, ge=0, le=1000)

    # Walk-forward specific
    param_grid: dict[str, list[Any]] = Field(
        ...,
        description='Param grid, e.g. {"slow_period": [20, 50, 100], "fast_period": [5, 10]}',
    )
    train_bars: int = Field(..., gt=0, le=10000)
    test_bars: int = Field(..., gt=0, le=10000)
    num_windows: int = Field(..., gt=0, le=50)
    selection_metric: str = Field(
        default="sharpe",
        pattern=r"^(sharpe|sortino|total_return|calmar)$",
    )


class WalkforwardSummary(BaseModel):
    """Row in GET /walkforwards list."""
    id: UUID
    strategy_name: str
    symbols: list[str]
    bar_resolution: str
    status: str
    created_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None
    num_windows: int
    total_combos: int | None = None
    avg_test_sharpe: float | None = None
    avg_test_return_pct: float | None = None
    overfit_drop: float | None = None
    win_rate_windows_pct: float | None = None


class WalkforwardDetail(BaseModel):
    """Full payload for GET /walkforwards/{id}."""
    id: UUID
    strategy_name: str
    symbols: list[str]
    bar_resolution: str
    starting_cash: Decimal
    fee_rate_bps: int
    slippage_bps: int
    param_grid: dict[str, list[Any]]
    train_bars: int
    test_bars: int
    num_windows: int
    selection_metric: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    total_combos: int | None = None
    total_backtests_run: int | None = None
    windows_result: list[dict[str, Any]] | None = None
    avg_train_sharpe: float | None = None
    avg_test_sharpe: float | None = None
    avg_test_return_pct: float | None = None
    overfit_drop: float | None = None
    win_rate_windows_pct: float | None = None


# ============================================================
# Redis client (one per process, lazy)
# ============================================================
_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


# ============================================================
# Helpers
# ============================================================
def _row_to_summary(row: dict[str, Any]) -> WalkforwardSummary:
    return WalkforwardSummary(
        id=row["id"],
        strategy_name=row["strategy_name"],
        symbols=list(row["symbols"]),
        bar_resolution=row["bar_resolution"],
        status=row["status"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        completed_at=row["completed_at"].isoformat() if row.get("completed_at") else None,
        duration_seconds=float(row["duration_seconds"]) if row.get("duration_seconds") is not None else None,
        num_windows=int(row["num_windows"]),
        total_combos=int(row["total_combos"]) if row.get("total_combos") is not None else None,
        avg_test_sharpe=float(row["avg_test_sharpe"]) if row.get("avg_test_sharpe") is not None else None,
        avg_test_return_pct=float(row["avg_test_return_pct"]) if row.get("avg_test_return_pct") is not None else None,
        overfit_drop=float(row["overfit_drop"]) if row.get("overfit_drop") is not None else None,
        win_rate_windows_pct=float(row["win_rate_windows_pct"]) if row.get("win_rate_windows_pct") is not None else None,
    )


def _row_to_detail(row: dict[str, Any]) -> WalkforwardDetail:
    return WalkforwardDetail(
        id=row["id"],
        strategy_name=row["strategy_name"],
        symbols=list(row["symbols"]),
        bar_resolution=row["bar_resolution"],
        starting_cash=Decimal(str(row["starting_cash"])),
        fee_rate_bps=int(row["fee_rate_bps"]),
        slippage_bps=int(row["slippage_bps"]),
        param_grid=row["param_grid"] if isinstance(row["param_grid"], dict) else {},
        train_bars=int(row["train_bars"]),
        test_bars=int(row["test_bars"]),
        num_windows=int(row["num_windows"]),
        selection_metric=row["selection_metric"],
        status=row["status"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        started_at=row["started_at"].isoformat() if row.get("started_at") else None,
        completed_at=row["completed_at"].isoformat() if row.get("completed_at") else None,
        duration_seconds=float(row["duration_seconds"]) if row.get("duration_seconds") is not None else None,
        error_message=row.get("error_message"),
        total_combos=int(row["total_combos"]) if row.get("total_combos") is not None else None,
        total_backtests_run=int(row["total_backtests_run"]) if row.get("total_backtests_run") is not None else None,
        windows_result=row["windows_result"] if isinstance(row.get("windows_result"), list) else None,
        avg_train_sharpe=float(row["avg_train_sharpe"]) if row.get("avg_train_sharpe") is not None else None,
        avg_test_sharpe=float(row["avg_test_sharpe"]) if row.get("avg_test_sharpe") is not None else None,
        avg_test_return_pct=float(row["avg_test_return_pct"]) if row.get("avg_test_return_pct") is not None else None,
        overfit_drop=float(row["overfit_drop"]) if row.get("overfit_drop") is not None else None,
        win_rate_windows_pct=float(row["win_rate_windows_pct"]) if row.get("win_rate_windows_pct") is not None else None,
    )


# ============================================================
# Endpoints
# ============================================================
@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_walkforward_endpoint(
    body: CreateWalkforwardRequest,
    user: Any = Depends(get_current_user_record),
):
    """Create a walk-forward job, persist it, and enqueue for the worker."""
    # Light sanity checks
    if body.test_bars > body.train_bars:
        raise HTTPException(
            status_code=400,
            detail="test_bars must not exceed train_bars",
        )
    if not body.param_grid:
        raise HTTPException(
            status_code=400,
            detail="param_grid must contain at least one parameter",
        )
    for name, values in body.param_grid.items():
        if not isinstance(values, list) or len(values) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"param_grid[{name!r}] must be a non-empty list",
            )

    walkforward_id = uuid4()
    engine: AsyncEngine = get_engine()

    async with engine.begin() as conn:
        await create_walkforward(
            conn,
            walkforward_id=walkforward_id,
            user_id=user.id,
            strategy_name=body.strategy_name,
            symbols=body.symbols,
            bar_resolution=body.bar_resolution,
            starting_cash=body.starting_cash,
            fee_rate_bps=body.fee_rate_bps,
            slippage_bps=body.slippage_bps,
            param_grid=body.param_grid,
            train_bars=body.train_bars,
            test_bars=body.test_bars,
            num_windows=body.num_windows,
            selection_metric=body.selection_metric,
        )

    # Enqueue
    r = _get_redis()
    await r.lpush(QUEUE_WALKFORWARD_JOBS, str(walkforward_id))

    return {"id": str(walkforward_id), "status": "pending"}


@router.get("", response_model=list[WalkforwardSummary])
async def list_walkforwards_endpoint(
    user: Any = Depends(get_current_user_record),
):
    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        rows = await list_walkforwards_for_user(conn, user.id)
    return [_row_to_summary(r) for r in rows]


@router.get("/{walkforward_id}", response_model=WalkforwardDetail)
async def get_walkforward_endpoint(
    walkforward_id: UUID,
    user: Any = Depends(get_current_user_record),
):
    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        row = await load_walkforward(conn, walkforward_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Walkforward not found")
    if str(row["user_id"]) != str(user.id):
        # Don't leak existence — return same 404
        raise HTTPException(status_code=404, detail="Walkforward not found")
    return _row_to_detail(row)
