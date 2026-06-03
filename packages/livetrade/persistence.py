"""CRUD for the paper_* tables.

Mirrors packages/backtest/persistence.py: functions take an AsyncConnection or
AsyncSession and the caller owns the transaction. The API uses these for
create/list/read; the paper_trader runner uses them to advance sessions and
record orders/fills/positions/equity.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


# ============================================================
# Sessions
# ============================================================
async def create_paper_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    api_credential_id: UUID,
    strategy_name: str,
    params_json: dict[str, Any],
    symbols: list[str],
    asset_class: str,
    bar_resolution: str,
    starting_cash: Decimal,
    max_order_notional: Decimal | None,
    cancel_open_on_stop: bool,
    mode: str = "paper",
    max_daily_loss: Decimal | None = None,
) -> UUID:
    """Insert a paper_session in 'starting' status. Returns its id."""
    result = await session.execute(
        text(
            """
            INSERT INTO paper_sessions (
                user_id, org_id, api_credential_id, strategy_name, params_json,
                symbols, asset_class, bar_resolution, starting_cash,
                max_order_notional, cancel_open_on_stop, mode, max_daily_loss,
                status
            ) VALUES (
                :user_id, :org_id, :api_credential_id, :strategy_name,
                CAST(:params_json AS jsonb), :symbols, :asset_class,
                :bar_resolution, :starting_cash, :max_order_notional,
                :cancel_open_on_stop, :mode, :max_daily_loss, 'starting'
            )
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "org_id": org_id,
            "api_credential_id": api_credential_id,
            "strategy_name": strategy_name,
            "params_json": _json(params_json),
            "symbols": symbols,
            "asset_class": asset_class,
            "bar_resolution": bar_resolution,
            "starting_cash": starting_cash,
            "max_order_notional": max_order_notional,
            "cancel_open_on_stop": cancel_open_on_stop,
            "mode": mode,
            "max_daily_loss": max_daily_loss,
        },
    )
    return result.scalar_one()


async def load_paper_session(
    conn: AsyncConnection | AsyncSession, session_id: UUID
) -> dict[str, Any] | None:
    result = await conn.execute(
        text("SELECT * FROM paper_sessions WHERE id = :id"),
        {"id": session_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_paper_sessions_for_user(
    conn: AsyncConnection | AsyncSession,
    user_id: UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT * FROM paper_sessions
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return [dict(r) for r in result.mappings()]


async def load_active_paper_sessions(
    conn: AsyncConnection | AsyncSession,
    *,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    """Sessions the runner should own/resume. Sharded by id when shard_count>1."""
    result = await conn.execute(
        text(
            """
            SELECT * FROM paper_sessions
            WHERE status IN ('starting', 'running', 'stopping')
            ORDER BY created_at
            """
        )
    )
    rows = [dict(r) for r in result.mappings()]
    if shard_count <= 1:
        return rows
    return [r for r in rows if int(r["id"].int) % shard_count == shard_index]


async def mark_session_running(
    conn: AsyncConnection, session_id: UUID, *, initialized: bool
) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_sessions
            SET status = 'running',
                initialized = :initialized,
                started_at = COALESCE(started_at, now()),
                error_message = NULL
            WHERE id = :id
            """
        ),
        {"id": session_id, "initialized": initialized},
    )


async def mark_session_stopped(conn: AsyncConnection, session_id: UUID) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_sessions
            SET status = 'stopped', stopped_at = now()
            WHERE id = :id
            """
        ),
        {"id": session_id},
    )


async def mark_session_error(
    conn: AsyncConnection, session_id: UUID, message: str
) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_sessions
            SET status = 'error', error_message = :msg, stopped_at = now()
            WHERE id = :id
            """
        ),
        {"id": session_id, "msg": message[:4000]},
    )


async def set_session_status(
    conn: AsyncConnection, session_id: UUID, status: str
) -> None:
    await conn.execute(
        text("UPDATE paper_sessions SET status = :s WHERE id = :id"),
        {"id": session_id, "s": status},
    )


async def advance_session_watermark(
    conn: AsyncConnection,
    session_id: UUID,
    *,
    last_processed_bar_ts: Any,
    last_bar_count: int,
    strategy_state_json: dict[str, Any],
) -> None:
    """Persist the runner's per-session watermark + strategy state."""
    await conn.execute(
        text(
            """
            UPDATE paper_sessions
            SET last_processed_bar_ts = :ts,
                last_bar_count = :bar_count,
                strategy_state_json = CAST(:state AS jsonb)
            WHERE id = :id
            """
        ),
        {
            "id": session_id,
            "ts": last_processed_bar_ts,
            "bar_count": last_bar_count,
            "state": _json(strategy_state_json),
        },
    )


async def update_session_summary(
    conn: AsyncConnection,
    session_id: UUID,
    *,
    current_equity: Decimal | None = None,
    realized_pnl: Decimal | None = None,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_sessions
            SET current_equity = COALESCE(:eq, current_equity),
                realized_pnl = COALESCE(:rpnl, realized_pnl)
            WHERE id = :id
            """
        ),
        {"id": session_id, "eq": current_equity, "rpnl": realized_pnl},
    )


# ============================================================
# Orders
# ============================================================
async def insert_paper_order(
    conn: AsyncConnection,
    *,
    session_id: UUID,
    client_order_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: Decimal,
    limit_price: Decimal | None,
    time_in_force: str,
    bar_count: int,
    expires_at_bar_count: int | None,
    submitted_ts: Any,
    status: str = "pending",
    error_message: str | None = None,
) -> UUID:
    result = await conn.execute(
        text(
            """
            INSERT INTO paper_orders (
                session_id, client_order_id, symbol, side, order_type, quantity,
                limit_price, time_in_force, bar_count, expires_at_bar_count,
                submitted_ts, status, error_message
            ) VALUES (
                :session_id, :coid, :symbol, :side, :order_type, :quantity,
                :limit_price, :tif, :bar_count, :expires, :submitted_ts,
                :status, :error_message
            )
            ON CONFLICT (client_order_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "session_id": session_id,
            "coid": client_order_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": limit_price,
            "tif": time_in_force,
            "bar_count": bar_count,
            "expires": expires_at_bar_count,
            "submitted_ts": submitted_ts,
            "status": status,
            "error_message": error_message,
        },
    )
    row = result.first()
    if row is not None:
        await conn.execute(
            text(
                "UPDATE paper_sessions SET num_orders = num_orders + 1 WHERE id = :id"
            ),
            {"id": session_id},
        )
        return row[0]
    # Conflict: order already exists (idempotent re-run) — return existing id.
    existing = await conn.execute(
        text("SELECT id FROM paper_orders WHERE client_order_id = :coid"),
        {"coid": client_order_id},
    )
    return existing.scalar_one()


async def set_order_broker_id(
    conn: AsyncConnection, order_id: UUID, broker_order_id: str, status: str
) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_orders
            SET broker_order_id = :bid, status = :status, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": order_id, "bid": broker_order_id, "status": status},
    )


async def mark_order_status(
    conn: AsyncConnection,
    order_id: UUID,
    status: str,
    *,
    filled_quantity: Decimal | None = None,
    avg_fill_price: Decimal | None = None,
    error_message: str | None = None,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE paper_orders
            SET status = :status,
                filled_quantity = COALESCE(:fq, filled_quantity),
                avg_fill_price = COALESCE(:afp, avg_fill_price),
                error_message = COALESCE(:err, error_message),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": order_id,
            "status": status,
            "fq": filled_quantity,
            "afp": avg_fill_price,
            "err": error_message,
        },
    )


async def get_order_by_client_id(
    conn: AsyncConnection | AsyncSession, client_order_id: str
) -> dict[str, Any] | None:
    result = await conn.execute(
        text("SELECT * FROM paper_orders WHERE client_order_id = :coid"),
        {"coid": client_order_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def load_open_orders(
    conn: AsyncConnection | AsyncSession, session_id: UUID
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT * FROM paper_orders
            WHERE session_id = :sid
              AND status IN ('pending', 'accepted', 'partially_filled')
            ORDER BY created_at
            """
        ),
        {"sid": session_id},
    )
    return [dict(r) for r in result.mappings()]


async def list_orders(
    conn: AsyncConnection | AsyncSession, session_id: UUID, *, limit: int = 200
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT * FROM paper_orders
            WHERE session_id = :sid
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"sid": session_id, "limit": limit},
    )
    return [dict(r) for r in result.mappings()]


# ============================================================
# Fills
# ============================================================
async def insert_paper_fill(
    conn: AsyncConnection,
    *,
    session_id: UUID,
    order_id: UUID,
    broker_fill_id: str | None,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
    filled_ts: Any,
) -> bool:
    """Insert a fill, deduped on (order_id, broker_fill_id). Returns True if new."""
    result = await conn.execute(
        text(
            """
            INSERT INTO paper_fills (
                session_id, order_id, broker_fill_id, symbol, side,
                quantity, price, fee, filled_ts
            ) VALUES (
                :sid, :oid, :bfid, :symbol, :side, :qty, :price, :fee, :ts
            )
            ON CONFLICT (order_id, broker_fill_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "sid": session_id,
            "oid": order_id,
            "bfid": broker_fill_id,
            "symbol": symbol,
            "side": side,
            "qty": quantity,
            "price": price,
            "fee": fee,
            "ts": filled_ts,
        },
    )
    inserted = result.first() is not None
    if inserted:
        await conn.execute(
            text(
                "UPDATE paper_sessions SET num_fills = num_fills + 1 WHERE id = :id"
            ),
            {"id": session_id},
        )
    return inserted


async def list_fills(
    conn: AsyncConnection | AsyncSession, session_id: UUID, *, limit: int = 500
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT * FROM paper_fills
            WHERE session_id = :sid
            ORDER BY filled_ts DESC
            LIMIT :limit
            """
        ),
        {"sid": session_id, "limit": limit},
    )
    return [dict(r) for r in result.mappings()]


# ============================================================
# Positions
# ============================================================
async def upsert_position(
    conn: AsyncConnection,
    *,
    session_id: UUID,
    symbol: str,
    quantity: Decimal,
    avg_cost: Decimal,
    realized_pnl: Decimal,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO paper_positions (session_id, symbol, quantity, avg_cost,
                                         realized_pnl, updated_at)
            VALUES (:sid, :symbol, :qty, :avg_cost, :rpnl, now())
            ON CONFLICT (session_id, symbol) DO UPDATE
                SET quantity = EXCLUDED.quantity,
                    avg_cost = EXCLUDED.avg_cost,
                    realized_pnl = EXCLUDED.realized_pnl,
                    updated_at = now()
            """
        ),
        {
            "sid": session_id,
            "symbol": symbol,
            "qty": quantity,
            "avg_cost": avg_cost,
            "rpnl": realized_pnl,
        },
    )


async def load_positions(
    conn: AsyncConnection | AsyncSession, session_id: UUID
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text("SELECT * FROM paper_positions WHERE session_id = :sid ORDER BY symbol"),
        {"sid": session_id},
    )
    return [dict(r) for r in result.mappings()]


# ============================================================
# Equity points
# ============================================================
async def insert_equity_point(
    conn: AsyncConnection,
    *,
    session_id: UUID,
    ts: Any,
    cash: Decimal,
    positions_value: Decimal,
    total_equity: Decimal,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO paper_equity_points (session_id, ts, cash,
                                             positions_value, total_equity)
            VALUES (:sid, :ts, :cash, :pv, :te)
            ON CONFLICT (session_id, ts) DO UPDATE
                SET cash = EXCLUDED.cash,
                    positions_value = EXCLUDED.positions_value,
                    total_equity = EXCLUDED.total_equity
            """
        ),
        {
            "sid": session_id,
            "ts": ts,
            "cash": cash,
            "pv": positions_value,
            "te": total_equity,
        },
    )


async def load_equity_points(
    conn: AsyncConnection | AsyncSession, session_id: UUID
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            "SELECT * FROM paper_equity_points WHERE session_id = :sid ORDER BY ts"
        ),
        {"sid": session_id},
    )
    return [dict(r) for r in result.mappings()]


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, default=str)
