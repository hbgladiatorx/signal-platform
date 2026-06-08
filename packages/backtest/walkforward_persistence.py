"""Persistence layer for walk-forward jobs.

Mirrors packages/backtest/persistence.py in shape — load/mark_running/
save_results/mark_failed — so the worker code can stay symmetric.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from packages.backtest.walkforward import WalkforwardResult, windows_to_json


# ============================================================
# Create
# ============================================================
async def create_walkforward(
    conn: AsyncConnection,
    *,
    walkforward_id: UUID,
    user_id: UUID,
    strategy_name: str,
    symbols: list[str],
    bar_resolution: str,
    starting_cash: Decimal,
    fee_rate_bps: int,
    slippage_bps: int,
    param_grid: dict[str, list[Any]],
    train_bars: int,
    test_bars: int,
    num_windows: int,
    selection_metric: str,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO walkforwards (
                id, user_id,
                strategy_name, symbols, bar_resolution,
                starting_cash, fee_rate_bps, slippage_bps,
                param_grid, train_bars, test_bars, num_windows,
                selection_metric, status
            ) VALUES (
                :id, :user_id,
                :strategy_name, :symbols, :bar_resolution,
                :starting_cash, :fee_rate_bps, :slippage_bps,
                :param_grid, :train_bars, :test_bars, :num_windows,
                :selection_metric, 'pending'
            )
            """
        ),
        {
            "id": str(walkforward_id),
            "user_id": str(user_id),
            "strategy_name": strategy_name,
            "symbols": symbols,
            "bar_resolution": bar_resolution,
            "starting_cash": starting_cash,
            "fee_rate_bps": fee_rate_bps,
            "slippage_bps": slippage_bps,
            "param_grid": json.dumps(param_grid),
            "train_bars": train_bars,
            "test_bars": test_bars,
            "num_windows": num_windows,
            "selection_metric": selection_metric,
        },
    )


# ============================================================
# Read
# ============================================================
async def load_walkforward(
    conn: AsyncConnection, walkforward_id: UUID
) -> dict[str, Any] | None:
    result = await conn.execute(
        text(
            """
            SELECT id, user_id,
                   strategy_name, symbols, bar_resolution,
                   starting_cash, fee_rate_bps, slippage_bps,
                   param_grid, train_bars, test_bars, num_windows,
                   selection_metric, status,
                   created_at, started_at, completed_at, duration_seconds,
                   error_message,
                   total_combos, total_backtests_run, windows_result,
                   avg_train_sharpe, avg_test_sharpe, avg_test_return_pct,
                   overfit_drop, win_rate_windows_pct
            FROM walkforwards
            WHERE id = :id
            """
        ),
        {"id": str(walkforward_id)},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return dict(row)


async def list_walkforwards_for_user(
    conn: AsyncConnection,
    user_id: UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT id, strategy_name, symbols, bar_resolution,
                   status, created_at, completed_at, duration_seconds,
                   num_windows, total_combos,
                   avg_test_sharpe, avg_test_return_pct,
                   overfit_drop, win_rate_windows_pct
            FROM walkforwards
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"user_id": str(user_id), "limit": limit},
    )
    return [dict(r) for r in result.mappings().all()]


# ============================================================
# Status transitions
# ============================================================
async def mark_walkforward_running(
    conn: AsyncConnection, walkforward_id: UUID
) -> None:
    await conn.execute(
        text(
            """
            UPDATE walkforwards
            SET status = 'running',
                started_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(walkforward_id)},
    )


async def reclaim_stale_walkforwards(
    conn: AsyncConnection,
    stale_after_seconds: int = 1800,
) -> list[UUID]:
    """Fail walk-forwards stranded in 'running' past the staleness threshold.

    Same orphan problem as backtests: a worker killed mid-run leaves the row
    in 'running' forever. Swept on worker startup, gated on `started_at` age so
    a sibling worker's in-flight run is untouched. Returns reclaimed ids.
    """
    result = await conn.execute(
        text(
            """
            UPDATE walkforwards
            SET status = 'failed',
                completed_at = now(),
                duration_seconds = EXTRACT(
                    EPOCH FROM (now() - COALESCE(started_at, created_at))
                ),
                error_message = 'Worker process exited while running (orphaned '
                                'job, likely OOM or restart); failed by startup '
                                'recovery.'
            WHERE status = 'running'
              AND COALESCE(started_at, created_at)
                  < now() - make_interval(secs => :stale_after)
            RETURNING id
            """
        ),
        {"stale_after": stale_after_seconds},
    )
    return [row[0] for row in result.all()]


async def mark_walkforward_failed(
    conn: AsyncConnection,
    walkforward_id: UUID,
    error_message: str,
) -> None:
    truncated = (error_message or "")[:4000]
    await conn.execute(
        text(
            """
            UPDATE walkforwards
            SET status = 'failed',
                completed_at = now(),
                duration_seconds = EXTRACT(EPOCH FROM (now() - COALESCE(started_at, created_at))),
                error_message = :err
            WHERE id = :id
            """
        ),
        {"id": str(walkforward_id), "err": truncated},
    )


async def save_walkforward_results(
    conn: AsyncConnection,
    walkforward_id: UUID,
    result: WalkforwardResult,
) -> None:
    """Persist completed walk-forward results."""
    await conn.execute(
        text(
            """
            UPDATE walkforwards
            SET status = 'completed',
                completed_at = now(),
                duration_seconds = :duration_seconds,
                total_combos = :total_combos,
                total_backtests_run = :total_backtests_run,
                windows_result = :windows_result,
                avg_train_sharpe = :avg_train_sharpe,
                avg_test_sharpe = :avg_test_sharpe,
                avg_test_return_pct = :avg_test_return_pct,
                overfit_drop = :overfit_drop,
                win_rate_windows_pct = :win_rate_windows_pct
            WHERE id = :id
            """
        ),
        {
            "id": str(walkforward_id),
            "duration_seconds": result.duration_seconds,
            "total_combos": result.total_combos,
            "total_backtests_run": result.total_backtests_run,
            "windows_result": json.dumps(windows_to_json(result.windows)),
            "avg_train_sharpe": result.avg_train_sharpe,
            "avg_test_sharpe": result.avg_test_sharpe,
            "avg_test_return_pct": result.avg_test_return_pct,
            "overfit_drop": result.overfit_drop,
            "win_rate_windows_pct": result.win_rate_windows_pct,
        },
    )
