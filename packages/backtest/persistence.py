"""Persistence layer for backtest runs.

Maps `BacktestResult` + `BacktestAnalytics` ↔ DB rows in:
  - backtests             (header, config, denormalized summary metrics)
  - backtest_trades       (closed round trips)
  - backtest_equity_points (equity curve samples)

All functions take an `AsyncConnection` so callers control transactions.
Typical usage pattern:

    async with engine.begin() as conn:           # one transaction
        bt_id = await create_backtest(conn, ...)
    # ... worker runs the backtest in process ...
    async with engine.begin() as conn:
        await mark_backtest_running(conn, bt_id)
    # ... compute ...
    async with engine.begin() as conn:
        await save_backtest_results(conn, bt_id, result, analytics, ...)

Or on failure:
    async with engine.begin() as conn:
        await mark_backtest_failed(conn, bt_id, "load_bars: no data for SYMBOL")
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from packages.backtest.analytics import BacktestAnalytics
from packages.backtest.types import BacktestResult


# ============================================================
# Create / lifecycle
# ============================================================
async def create_backtest(
    conn: AsyncConnection,
    *,
    user_id: UUID,
    org_id: UUID,
    strategy_name: str,
    params_json: dict[str, Any],
    symbols: list[str],
    bar_resolution: str,
    starting_cash: Decimal,
    fee_rate_bps: int = 10,
    slippage_bps: int = 5,
) -> UUID:
    """Insert a new backtest row in 'pending' state. Returns the new id."""
    result = await conn.execute(
        text("""
            INSERT INTO backtests (
                user_id, org_id, strategy_name, params_json,
                symbols, bar_resolution, starting_cash,
                fee_rate_bps, slippage_bps, status
            ) VALUES (
                :user_id, :org_id, :strategy_name,
                CAST(:params_json AS JSONB),
                :symbols, :bar_resolution, :starting_cash,
                :fee_rate_bps, :slippage_bps, 'pending'
            ) RETURNING id
        """),
        {
            "user_id": user_id,
            "org_id": org_id,
            "strategy_name": strategy_name,
            "params_json": json.dumps(params_json),
            "symbols": symbols,
            "bar_resolution": bar_resolution,
            "starting_cash": starting_cash,
            "fee_rate_bps": fee_rate_bps,
            "slippage_bps": slippage_bps,
        },
    )
    return result.scalar_one()


async def mark_backtest_running(
    conn: AsyncConnection, backtest_id: UUID
) -> None:
    """Transition backtest from pending → running; stamps started_at."""
    await conn.execute(
        text("""
            UPDATE backtests
            SET status = 'running',
                started_at = now()
            WHERE id = :id
        """),
        {"id": backtest_id},
    )


async def mark_backtest_failed(
    conn: AsyncConnection,
    backtest_id: UUID,
    error_message: str,
) -> None:
    """Transition to failed; stamps completed_at, duration_seconds, error."""
    # Truncate error message to a reasonable length so a Python traceback
    # doesn't blow up the column.
    msg = error_message[:5000]
    await conn.execute(
        text("""
            UPDATE backtests
            SET status = 'failed',
                completed_at = now(),
                error_message = :error_message,
                duration_seconds = EXTRACT(
                    EPOCH FROM (now() - COALESCE(started_at, created_at))
                )
            WHERE id = :id
        """),
        {"id": backtest_id, "error_message": msg},
    )


# ============================================================
# Result persistence
# ============================================================
def _opt_float(v: float | int | Decimal | None) -> float | None:
    return float(v) if v is not None else None


async def save_backtest_results(
    conn: AsyncConnection,
    backtest_id: UUID,
    result: BacktestResult,
    analytics: BacktestAnalytics,
    *,
    bars_start: datetime | None = None,
    bars_end: datetime | None = None,
    num_bars: int | None = None,
) -> None:
    """Persist a completed backtest: update header, insert trades + equity.

    Caller is expected to wrap this in a single transaction so partial
    writes can't leave the DB in an inconsistent state.
    """
    # ----- Update header: status, summary metrics -----
    await conn.execute(
        text("""
            UPDATE backtests SET
                status = 'completed',
                completed_at = now(),
                duration_seconds = EXTRACT(
                    EPOCH FROM (now() - COALESCE(started_at, created_at))
                ),
                bars_start = :bars_start,
                bars_end = :bars_end,
                num_bars = :num_bars,
                total_return_pct = :total_return_pct,
                annualized_return_pct = :annualized_return_pct,
                sharpe_ratio = :sharpe_ratio,
                sortino_ratio = :sortino_ratio,
                max_drawdown_pct = :max_drawdown_pct,
                calmar_ratio = :calmar_ratio,
                num_closed_trades = :num_closed_trades,
                num_open_trades = :num_open_trades,
                win_rate_pct = :win_rate_pct,
                profit_factor = :profit_factor
            WHERE id = :id
        """),
        {
            "id": backtest_id,
            "bars_start": bars_start,
            "bars_end": bars_end,
            "num_bars": num_bars,
            "total_return_pct": _opt_float(analytics.total_return_pct),
            "annualized_return_pct": _opt_float(analytics.annualized_return_pct),
            "sharpe_ratio": _opt_float(analytics.sharpe_ratio),
            "sortino_ratio": _opt_float(analytics.sortino_ratio),
            "max_drawdown_pct": _opt_float(analytics.max_drawdown_pct),
            "calmar_ratio": _opt_float(analytics.calmar_ratio),
            "num_closed_trades": analytics.num_closed_trades,
            "num_open_trades": analytics.num_open_trades,
            "win_rate_pct": _opt_float(analytics.win_rate_pct),
            "profit_factor": _opt_float(analytics.profit_factor),
        },
    )

    # ----- Trades (closed round trips) -----
    if analytics.closed_round_trips:
        trade_rows = [
            {
                "backtest_id": backtest_id,
                "symbol": rt.symbol,
                "side": rt.side,
                "entry_ts": rt.entry_ts,
                "exit_ts": rt.exit_ts,
                "entry_avg_price": rt.entry_avg_price,
                "exit_avg_price": rt.exit_avg_price,
                "quantity": rt.quantity,
                "gross_pnl": rt.gross_pnl,
                "fees": rt.fees,
                "net_pnl": rt.net_pnl,
                "duration_seconds": rt.duration_seconds,
                "num_fills": rt.num_fills,
            }
            for rt in analytics.closed_round_trips
        ]
        await conn.execute(
            text("""
                INSERT INTO backtest_trades (
                    backtest_id, symbol, side,
                    entry_ts, exit_ts,
                    entry_avg_price, exit_avg_price, quantity,
                    gross_pnl, fees, net_pnl,
                    duration_seconds, num_fills
                ) VALUES (
                    :backtest_id, :symbol, :side,
                    :entry_ts, :exit_ts,
                    :entry_avg_price, :exit_avg_price, :quantity,
                    :gross_pnl, :fees, :net_pnl,
                    :duration_seconds, :num_fills
                )
            """),
            trade_rows,
        )

    # ----- Equity points -----
    if result.equity_curve:
        BATCH = 1000
        equity_rows = [
            {
                "backtest_id": backtest_id,
                "ts": ep.ts,
                "cash": ep.cash,
                "positions_value": ep.positions_value,
                "total_equity": ep.total_equity,
            }
            for ep in result.equity_curve
        ]
        for i in range(0, len(equity_rows), BATCH):
            chunk = equity_rows[i:i + BATCH]
            await conn.execute(
                text("""
                    INSERT INTO backtest_equity_points (
                        backtest_id, ts, cash, positions_value, total_equity
                    ) VALUES (
                        :backtest_id, :ts, :cash, :positions_value, :total_equity
                    )
                """),
                chunk,
            )


# ============================================================
# Loaders (for the worker and API)
# ============================================================
async def load_backtest(
    conn: AsyncConnection, backtest_id: UUID
) -> dict[str, Any] | None:
    """Load a backtest header by id. Returns None if not found."""
    result = await conn.execute(
        text("SELECT * FROM backtests WHERE id = :id"),
        {"id": backtest_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_backtests_for_user(
    conn: AsyncConnection,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Most-recent-first backtests for a user."""
    result = await conn.execute(
        text("""
            SELECT
                id, strategy_name, symbols, bar_resolution, status,
                created_at, completed_at, duration_seconds,
                bars_start, bars_end, num_bars,
                total_return_pct, sharpe_ratio, max_drawdown_pct,
                num_closed_trades, win_rate_pct
            FROM backtests
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings().all()]


async def load_backtest_trades(
    conn: AsyncConnection, backtest_id: UUID
) -> list[dict[str, Any]]:
    """All round trips for a backtest, in exit-time order."""
    result = await conn.execute(
        text("""
            SELECT *
            FROM backtest_trades
            WHERE backtest_id = :id
            ORDER BY exit_ts
        """),
        {"id": backtest_id},
    )
    return [dict(row) for row in result.mappings().all()]


async def load_backtest_equity(
    conn: AsyncConnection, backtest_id: UUID
) -> list[dict[str, Any]]:
    """Full equity curve for a backtest, time-ordered."""
    result = await conn.execute(
        text("""
            SELECT ts, cash, positions_value, total_equity
            FROM backtest_equity_points
            WHERE backtest_id = :id
            ORDER BY ts
        """),
        {"id": backtest_id},
    )
    return [dict(row) for row in result.mappings().all()]


async def delete_backtest(
    conn: AsyncConnection, backtest_id: UUID, user_id: UUID
) -> bool:
    """Delete a backtest, scoped to its owner.

    The backtest_trades and backtest_equity_points rows are removed
    automatically via their ON DELETE CASCADE foreign keys. Returns True if a
    row was actually deleted (False if it didn't exist or isn't the user's).
    """
    result = await conn.execute(
        text("DELETE FROM backtests WHERE id = :id AND user_id = :user_id"),
        {"id": backtest_id, "user_id": user_id},
    )
    return result.rowcount > 0
