"""Trading endpoints — paper and live order execution.

Accounts:
  POST   /trading/accounts                  — create a paper or live account
  GET    /trading/accounts                  — list the current user's accounts
  GET    /trading/accounts/{id}             — one account
  GET    /trading/accounts/{id}/positions   — open positions for the account
  GET    /trading/accounts/{id}/balances    — balances (paper: tracked cash;
                                               live: pulled from the venue)

Orders:
  POST   /trading/orders                    — place an order (routes paper/live)
  GET    /trading/orders                    — list orders (optionally by account)
  GET    /trading/orders/{id}               — one order with its fills
  DELETE /trading/orders/{id}               — cancel a resting order

Live transmission additionally requires the BINANCEUS_LIVE_TRADING_ENABLED
kill-switch env flag; without it, live orders are persisted as 'rejected' with
an explanatory message rather than ever reaching the venue.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.db import get_engine
from packages.execution.base import BrokerError
from packages.execution.binance_broker import live_trading_enabled
from packages.execution.manager import TradingManager
from packages.execution.types import ExecutionMode, OrderType, Side
from services.api.deps import CurrentUserRecord, get_current_user_record, get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])


# ============================================================
# Schemas
# ============================================================
class CreateAccountRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    mode: Literal["paper", "live"]
    venue: str = Field(default="BINANCEUS")
    quote_currency: str = Field(default="USDT", min_length=2, max_length=12)
    starting_cash: Decimal = Field(default=Decimal("100000"), ge=0)
    fee_bps: int = Field(default=10, ge=0, le=1000)
    slippage_bps: int = Field(default=5, ge=0, le=1000)
    credential_id: UUID | None = Field(
        default=None,
        description="api_credentials row to sign live orders with. "
                    "If omitted, the user's stored binanceus key (or env) is used.",
    )


class AccountResponse(BaseModel):
    id: UUID
    name: str
    mode: str
    venue: str
    quote_currency: str
    starting_cash: Decimal
    cash_balance: Decimal
    fee_bps: int
    slippage_bps: int
    status: str
    created_at: datetime


class PlaceOrderRequest(BaseModel):
    account_id: UUID
    symbol: str = Field(..., description="Canonical symbol, e.g. BTC-USDT@BINANCEUS")
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"] = "market"
    quantity: Decimal = Field(..., gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)


class OrderResponse(BaseModel):
    id: UUID
    account_id: UUID
    canonical_symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    mode: str
    status: str
    filled_quantity: Decimal
    avg_fill_price: Decimal | None
    fees: Decimal
    fee_currency: str | None
    client_order_id: str
    venue_order_id: str | None
    error_message: str | None
    created_at: datetime


class FillResponse(BaseModel):
    ts: datetime
    price: Decimal
    quantity: Decimal
    fee: Decimal
    fee_currency: str | None
    venue_fill_id: str | None


class OrderDetailResponse(OrderResponse):
    fills: list[FillResponse] = Field(default_factory=list)


class PositionResponse(BaseModel):
    canonical_symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal


class BalanceResponse(BaseModel):
    asset: str
    free: Decimal
    locked: Decimal


# ============================================================
# Helpers
# ============================================================
def _order_row_to_response(row: dict[str, Any]) -> OrderResponse:
    return OrderResponse(
        id=row["id"],
        account_id=row["account_id"],
        canonical_symbol=row["canonical_symbol"],
        side=row["side"],
        order_type=row["order_type"],
        quantity=row["quantity"],
        limit_price=row.get("limit_price"),
        mode=row["mode"],
        status=row["status"],
        filled_quantity=row["filled_quantity"],
        avg_fill_price=row.get("avg_fill_price"),
        fees=row["fees"],
        fee_currency=row.get("fee_currency"),
        client_order_id=row["client_order_id"],
        venue_order_id=row.get("venue_order_id"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
    )


async def _load_account_or_404(
    session: AsyncSession, account_id: UUID, user: CurrentUserRecord
) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT * FROM trading_accounts WHERE id = :id"),
            {"id": account_id},
        )
    ).mappings().first()
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "Trading account not found")
    return dict(row)


# ============================================================
# Account endpoints
# ============================================================
@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    body: CreateAccountRequest,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> AccountResponse:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO trading_accounts (
                    user_id, org_id, name, mode, venue, quote_currency,
                    starting_cash, cash_balance, fee_bps, slippage_bps,
                    credential_id
                ) VALUES (
                    :user_id, :org_id, :name, :mode, :venue, :quote_currency,
                    :starting_cash, :starting_cash, :fee_bps, :slippage_bps,
                    :credential_id
                ) RETURNING *
                """
            ),
            {
                "user_id": user.id,
                "org_id": user.org_id,
                "name": body.name,
                "mode": body.mode,
                "venue": body.venue.upper(),
                "quote_currency": body.quote_currency.upper(),
                "starting_cash": body.starting_cash,
                "fee_bps": body.fee_bps,
                "slippage_bps": body.slippage_bps,
                "credential_id": body.credential_id,
            },
        )
    ).mappings().first()
    await session.commit()
    return AccountResponse(**dict(row))


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[AccountResponse]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM trading_accounts WHERE user_id = :uid "
                "ORDER BY created_at DESC"
            ),
            {"uid": user.id},
        )
    ).mappings().all()
    return [AccountResponse(**dict(r)) for r in rows]


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> AccountResponse:
    row = await _load_account_or_404(session, account_id, user)
    return AccountResponse(**row)


@router.get("/accounts/{account_id}/positions", response_model=list[PositionResponse])
async def get_account_positions(
    account_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[PositionResponse]:
    await _load_account_or_404(session, account_id, user)
    rows = (
        await session.execute(
            text(
                """
                SELECT canonical_symbol, quantity, avg_entry_price, realized_pnl
                FROM trading_positions
                WHERE account_id = :aid AND quantity <> 0
                ORDER BY canonical_symbol
                """
            ),
            {"aid": account_id},
        )
    ).mappings().all()
    return [PositionResponse(**dict(r)) for r in rows]


@router.get("/accounts/{account_id}/balances", response_model=list[BalanceResponse])
async def get_account_balances(
    account_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[BalanceResponse]:
    account = await _load_account_or_404(session, account_id, user)
    if account["mode"] == ExecutionMode.PAPER.value:
        return [
            BalanceResponse(
                asset=account["quote_currency"],
                free=account["cash_balance"],
                locked=Decimal("0"),
            )
        ]
    # Live: pull authoritative balances from the venue.
    manager = TradingManager(get_engine())
    try:
        broker = await manager.build_broker(session, account)
    except BrokerError as e:
        raise HTTPException(400, str(e))
    try:
        balances = await broker.get_balances()
    except BrokerError as e:
        raise HTTPException(502, f"Could not fetch venue balances: {e}")
    finally:
        await broker.close()
    return [
        BalanceResponse(asset=b.asset, free=b.free, locked=b.locked) for b in balances
    ]


# ============================================================
# Order endpoints
# ============================================================
@router.post("/orders", response_model=OrderResponse, status_code=201)
async def place_order(
    body: PlaceOrderRequest,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> OrderResponse:
    account = await _load_account_or_404(session, body.account_id, user)
    if account["status"] != "active":
        raise HTTPException(400, "Trading account is disabled")

    if body.order_type == "limit" and body.limit_price is None:
        raise HTTPException(422, "limit orders require limit_price")
    if body.order_type == "market" and body.limit_price is not None:
        raise HTTPException(422, "market orders must not include limit_price")

    instrument = (
        await session.execute(
            text(
                """
                SELECT id, canonical_symbol, native_symbol, base, quote, venue, active
                FROM instruments WHERE canonical_symbol = :sym
                """
            ),
            {"sym": body.symbol},
        )
    ).mappings().first()
    if instrument is None:
        raise HTTPException(
            422,
            f"Unknown symbol {body.symbol!r}. Sync the universe via "
            f"POST /instruments/sync/binanceus or add the instrument first.",
        )
    if instrument["venue"].upper() != account["venue"].upper():
        raise HTTPException(
            422,
            f"Symbol venue {instrument['venue']} does not match account venue "
            f"{account['venue']}",
        )

    manager = TradingManager(get_engine())
    try:
        order_row = await manager.place_order(
            session,
            account=account,
            instrument=dict(instrument),
            side=Side(body.side),
            order_type=OrderType(body.order_type),
            quantity=body.quantity,
            limit_price=body.limit_price,
        )
    except BrokerError as e:
        raise HTTPException(400, str(e))
    await session.commit()
    return _order_row_to_response(order_row)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    account_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[OrderResponse]:
    params: dict[str, Any] = {"uid": user.id, "limit": limit, "offset": offset}
    query = "SELECT * FROM orders WHERE user_id = :uid"
    if account_id is not None:
        query += " AND account_id = :aid"
        params["aid"] = account_id
    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    rows = (await session.execute(text(query), params)).mappings().all()
    return [_order_row_to_response(dict(r)) for r in rows]


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> OrderDetailResponse:
    row = (
        await session.execute(
            text("SELECT * FROM orders WHERE id = :id"), {"id": order_id}
        )
    ).mappings().first()
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "Order not found")
    fills = (
        await session.execute(
            text(
                """
                SELECT ts, price, quantity, fee, fee_currency, venue_fill_id
                FROM order_fills WHERE order_id = :id ORDER BY ts
                """
            ),
            {"id": order_id},
        )
    ).mappings().all()
    base = _order_row_to_response(dict(row))
    return OrderDetailResponse(
        **base.model_dump(),
        fills=[FillResponse(**dict(f)) for f in fills],
    )


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> OrderResponse:
    row = (
        await session.execute(
            text("SELECT * FROM orders WHERE id = :id"), {"id": order_id}
        )
    ).mappings().first()
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "Order not found")
    order = dict(row)
    if order["status"] in ("filled", "canceled", "rejected", "expired"):
        raise HTTPException(409, f"Order is already {order['status']}")
    account = await _load_account_or_404(session, order["account_id"], user)

    manager = TradingManager(get_engine())
    try:
        updated = await manager.cancel_order(session, account=account, order=order)
    except BrokerError as e:
        raise HTTPException(400, str(e))
    await session.commit()
    return _order_row_to_response(updated)


@router.get("/status")
async def trading_status(
    _user: CurrentUserRecord = Depends(get_current_user_record),
) -> dict[str, Any]:
    """Report execution-layer readiness (does not require an account)."""
    return {
        "paper_trading": "enabled",
        "live_trading_enabled": live_trading_enabled(),
        "live_venue": "BINANCEUS",
    }
