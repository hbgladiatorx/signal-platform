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
from packages.backtest.attribution import (
    BacktestAttribution,
    attribution_to_dict,
)
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
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> UUID:
    """Insert a new backtest row in 'pending' state. Returns the new id.

    window_start/window_end bound the requested date range (inclusive). NULL on
    both means "run over the symbol's full available history" — the worker only
    filters bars when a bound is set.
    """
    result = await conn.execute(
        text("""
            INSERT INTO backtests (
                user_id, org_id, strategy_name, params_json,
                symbols, bar_resolution, starting_cash,
                fee_rate_bps, slippage_bps, window_start, window_end, status
            ) VALUES (
                :user_id, :org_id, :strategy_name,
                CAST(:params_json AS JSONB),
                :symbols, :bar_resolution, :starting_cash,
                :fee_rate_bps, :slippage_bps, :window_start, :window_end, 'pending'
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
            "window_start": window_start,
            "window_end": window_end,
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


async def reclaim_stale_backtests(
    conn: AsyncConnection,
    stale_after_seconds: int = 1800,
) -> list[UUID]:
    """Fail backtests stuck in 'running' past the staleness threshold.

    A backtest only reaches 'running' inside `_process_job`. If the worker
    process is killed mid-run (OOM, container restart, SIGKILL), the
    try/except that would call `mark_backtest_failed` never executes, so the
    row is stranded in 'running' forever and the UI renders a fake all-zero
    result. Nothing else ever transitions it.

    On worker startup we sweep these orphans. We gate on `started_at` age
    rather than failing every 'running' row so a sibling worker's genuinely
    in-flight job (scale-out runs multiple containers) is left alone — real
    runs complete in seconds-to-minutes, far under the default 30-minute gate.

    Returns the ids that were reclaimed (for logging).
    """
    result = await conn.execute(
        text("""
            UPDATE backtests
            SET status = 'failed',
                completed_at = now(),
                error_message = 'Worker process exited while running (orphaned '
                                'job, likely OOM or restart); failed by startup '
                                'recovery.',
                duration_seconds = EXTRACT(
                    EPOCH FROM (now() - COALESCE(started_at, created_at))
                )
            WHERE status = 'running'
              AND COALESCE(started_at, created_at)
                  < now() - make_interval(secs => :stale_after)
            RETURNING id
        """),
        {"stale_after": stale_after_seconds},
    )
    return [row[0] for row in result.all()]


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
    attribution: BacktestAttribution | None = None,
    ml_model_json: dict | None = None,
    analysis_json: dict | None = None,
    bars_start: datetime | None = None,
    bars_end: datetime | None = None,
    num_bars: int | None = None,
) -> None:
    """Persist a completed backtest: update header, insert trades + equity.

    Caller is expected to wrap this in a single transaction so partial
    writes can't leave the DB in an inconsistent state.

    `attribution`, when supplied, is serialized into the backtests row's
    `attribution_json` column (the per-symbol / per-signal "why"). None leaves
    the column NULL — the detail view simply omits the attribution section.

    `ml_model_json` is the already-serialized signal-edge model dict (from
    `model_to_dict`); it is written to `ml_model_json`. None leaves it NULL.
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
                profit_factor = :profit_factor,
                attribution_json = CAST(:attribution_json AS JSONB),
                ml_model_json = CAST(:ml_model_json AS JSONB),
                analysis_json = CAST(:analysis_json AS JSONB)
            WHERE id = :id
        """),
        {
            "id": backtest_id,
            "attribution_json": (
                json.dumps(attribution_to_dict(attribution))
                if attribution is not None
                else None
            ),
            "ml_model_json": (
                json.dumps(ml_model_json) if ml_model_json is not None else None
            ),
            "analysis_json": (
                json.dumps(analysis_json) if analysis_json is not None else None
            ),
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
                num_closed_trades, win_rate_pct, profit_factor
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
