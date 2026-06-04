"""Paper-trading session API endpoints.

Endpoints (all JWT-protected, user-scoped):
  POST   /paper-sessions                 — create + start a live paper session
  GET    /paper-sessions                 — list current user's sessions
  GET    /paper-sessions/{id}            — one session header + summary
  GET    /paper-sessions/{id}/orders     — orders
  GET    /paper-sessions/{id}/fills      — fills
  GET    /paper-sessions/{id}/positions  — current positions
  GET    /paper-sessions/{id}/equity     — equity curve
  POST   /paper-sessions/{id}/stop       — stop the session
  POST   /paper-sessions/{id}/flatten    — emergency: market-sell all positions

Create flow mirrors backtests: resolve strategy, validate params + symbols +
the Alpaca credential, INSERT (status='starting'), then LPUSH a control message
to paper:control for the paper_trader runner.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.data.messagebus import QUEUE_PAPER_CONTROL
from packages.livetrade import persistence as P
from packages.strategy.loader import StrategyLoadError
from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy
from services.api.deps import (
    CurrentUserRecord,
    get_current_user_record,
    get_db_session,
)
from services.api.routers.backtests import _get_redis, _validate_symbols
from services.api.routers.strategies import get_strategy_registry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/paper-sessions", tags=["paper-trading"])

BarResolution = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
AssetClass = Literal["crypto_spot", "equity", "option"]


# ============================================================
# Request / response models
# ============================================================
class CreatePaperSessionRequest(BaseModel):
    strategy_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(..., min_length=1)
    asset_class: AssetClass = "crypto_spot"
    bar_resolution: BarResolution = "1m"
    api_credential_id: UUID
    starting_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    max_order_notional: Decimal | None = Field(default=None, gt=0)
    cancel_open_on_stop: bool = True
    # Live (real-money) guardrail. REQUIRED when the credential is a Binance.US
    # key (mode='live'); ignored for Alpaca paper sessions.
    max_daily_loss: Decimal | None = Field(default=None, gt=0)


class CreatePaperSessionResponse(BaseModel):
    id: UUID
    status: str


class PaperSessionSummary(BaseModel):
    id: UUID
    strategy_name: str
    symbols: list[str]
    asset_class: str
    bar_resolution: str
    mode: str = "paper"
    status: str
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    current_equity: Decimal | None = None
    realized_pnl: Decimal | None = None
    num_orders: int = 0
    num_fills: int = 0


class PaperSessionDetail(PaperSessionSummary):
    params_json: dict[str, Any]
    starting_cash: Decimal
    max_order_notional: Decimal | None = None
    max_daily_loss: Decimal | None = None
    cancel_open_on_stop: bool
    error_message: str | None = None
    last_processed_bar_ts: datetime | None = None
    last_bar_count: int = 0


class OrderRow(BaseModel):
    id: UUID
    client_order_id: str
    broker_order_id: str | None = None
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None = None
    time_in_force: str
    status: str
    filled_quantity: Decimal
    avg_fill_price: Decimal | None = None
    error_message: str | None = None
    submitted_ts: datetime
    created_at: datetime


class FillRow(BaseModel):
    id: int
    order_id: UUID
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_ts: datetime


class PositionRow(BaseModel):
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal
    updated_at: datetime


class EquityPointRow(BaseModel):
    ts: datetime
    cash: Decimal
    positions_value: Decimal
    total_equity: Decimal


# ============================================================
# Helpers
# ============================================================
# Trading venues a live session can route to, and the session mode each implies.
_TRADING_SERVICE_MODE: dict[str, str] = {
    "alpaca": "paper",       # Alpaca paper account — simulated funds
    "alpaca_live": "live",   # Alpaca live equities/options — REAL money
    "binanceus": "live",     # Binance.US spot — REAL money
}


async def _validate_trading_credential(
    session: AsyncSession, user_id: UUID, credential_id: UUID
) -> str:
    """Ensure the credential is the caller's and a supported trading venue.

    Returns the session `mode` ('paper' for Alpaca, 'live' for Binance.US).
    """
    result = await session.execute(
        text(
            "SELECT service FROM api_credentials "
            "WHERE id = :id AND user_id = :uid"
        ),
        {"id": credential_id, "uid": user_id},
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=422, detail="api_credential_id not found or not yours"
        )
    mode = _TRADING_SERVICE_MODE.get(row[0])
    if mode is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"credential service {row[0]!r} cannot place trades "
                "(expected an Alpaca or Binance.US key)"
            ),
        )
    return mode


async def _load_my_session_or_404(
    session: AsyncSession, session_id: UUID, user: CurrentUserRecord
) -> dict[str, Any]:
    row = await P.load_paper_session(session, session_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "Paper session not found")
    return row


async def _push_control(action: str, session_id: UUID) -> None:
    try:
        r = await _get_redis()
        await r.lpush(
            QUEUE_PAPER_CONTROL,
            orjson.dumps({"action": action, "session_id": str(session_id)}).decode(),
        )
    except Exception as e:  # noqa: BLE001
        log.error("paper_sessions.control_push_failed action=%s err=%s", action, e)


# ============================================================
# Endpoints
# ============================================================
@router.post("", response_model=CreatePaperSessionResponse, status_code=201)
async def create_paper_session(
    req: CreatePaperSessionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> CreatePaperSessionResponse:
    # Resolve strategy (built-in or this user's).
    try:
        resolved = await resolve_strategy(
            session,
            user_id=user.id,
            strategy_name=req.strategy_name,
            builtin_registry=get_strategy_registry(),
        )
    except StrategyNotFoundError:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": f"Unknown strategy: {req.strategy_name!r}",
                "available": sorted(get_strategy_registry().keys()),
            },
        )
    except StrategyLoadError as e:
        raise HTTPException(
            status_code=422,
            detail={"msg": f"Strategy {req.strategy_name!r} failed to compile",
                    "error": str(e)},
        )

    # Validate params against the strategy's schema.
    try:
        validated = resolved.cls.PARAMS_MODEL(**req.params)
    except ValidationError as e:
        import json as _json

        raise HTTPException(
            status_code=422,
            detail={"msg": "Invalid params", "errors": _json.loads(e.json())},
        )

    await _validate_symbols(session, req.symbols)
    mode = await _validate_trading_credential(session, user.id, req.api_credential_id)

    # Real money requires mandatory guardrails: a daily-loss halt and a
    # per-order notional cap.
    if mode == "live":
        if req.max_daily_loss is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "max_daily_loss is required for a live session — real money "
                    "will not trade without a daily-loss halt configured."
                ),
            )
        if req.max_order_notional is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "max_order_notional is required for a live session — real "
                    "money will not trade without a per-order notional cap."
                ),
            )

    session_id = await P.create_paper_session(
        session,
        user_id=user.id,
        org_id=user.org_id,
        api_credential_id=req.api_credential_id,
        strategy_name=req.strategy_name,
        params_json=validated.model_dump(),
        symbols=req.symbols,
        asset_class=req.asset_class,
        bar_resolution=req.bar_resolution,
        starting_cash=req.starting_cash,
        max_order_notional=req.max_order_notional,
        cancel_open_on_stop=req.cancel_open_on_stop,
        mode=mode,
        max_daily_loss=req.max_daily_loss,
    )
    await session.commit()

    await _push_control("start", session_id)
    return CreatePaperSessionResponse(id=session_id, status="starting")


@router.get("", response_model=list[PaperSessionSummary])
async def list_paper_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[PaperSessionSummary]:
    rows = await P.list_paper_sessions_for_user(
        session, user.id, limit=limit, offset=offset
    )
    return [PaperSessionSummary(**_summary_fields(r)) for r in rows]


@router.get("/{session_id}", response_model=PaperSessionDetail)
async def get_paper_session(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> PaperSessionDetail:
    row = await _load_my_session_or_404(session, session_id, user)
    return PaperSessionDetail(
        **_summary_fields(row),
        params_json=row["params_json"] or {},
        starting_cash=row["starting_cash"],
        max_order_notional=row.get("max_order_notional"),
        max_daily_loss=row.get("max_daily_loss"),
        cancel_open_on_stop=row["cancel_open_on_stop"],
        error_message=row.get("error_message"),
        last_processed_bar_ts=row.get("last_processed_bar_ts"),
        last_bar_count=row.get("last_bar_count") or 0,
    )


@router.get("/{session_id}/orders", response_model=list[OrderRow])
async def get_orders(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[OrderRow]:
    await _load_my_session_or_404(session, session_id, user)
    rows = await P.list_orders(session, session_id)
    return [OrderRow(**{k: r.get(k) for k in OrderRow.model_fields}) for r in rows]


@router.get("/{session_id}/fills", response_model=list[FillRow])
async def get_fills(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[FillRow]:
    await _load_my_session_or_404(session, session_id, user)
    rows = await P.list_fills(session, session_id)
    return [FillRow(**{k: r.get(k) for k in FillRow.model_fields}) for r in rows]


@router.get("/{session_id}/positions", response_model=list[PositionRow])
async def get_positions(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[PositionRow]:
    await _load_my_session_or_404(session, session_id, user)
    rows = await P.load_positions(session, session_id)
    return [PositionRow(**{k: r.get(k) for k in PositionRow.model_fields}) for r in rows]


@router.get("/{session_id}/equity", response_model=list[EquityPointRow])
async def get_equity(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[EquityPointRow]:
    await _load_my_session_or_404(session, session_id, user)
    rows = await P.load_equity_points(session, session_id)
    return [
        EquityPointRow(
            ts=r["ts"],
            cash=r["cash"],
            positions_value=r["positions_value"],
            total_equity=r["total_equity"],
        )
        for r in rows
    ]


@router.post("/{session_id}/stop", status_code=202)
async def stop_paper_session(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> dict[str, str]:
    await _load_my_session_or_404(session, session_id, user)
    await session.execute(
        text(
            "UPDATE paper_sessions SET status = 'stopping' "
            "WHERE id = :id AND status IN ('starting', 'running')"
        ),
        {"id": session_id},
    )
    await session.commit()
    await _push_control("stop", session_id)
    return {"status": "stopping"}


@router.post("/{session_id}/flatten", status_code=202)
async def flatten_paper_session(
    session_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> dict[str, str]:
    await _load_my_session_or_404(session, session_id, user)
    await _push_control("flatten", session_id)
    return {"status": "flattening"}


def _summary_fields(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "strategy_name": r["strategy_name"],
        "symbols": list(r["symbols"]),
        "asset_class": r["asset_class"],
        "bar_resolution": r["bar_resolution"],
        "mode": r.get("mode") or "paper",
        "status": r["status"],
        "created_at": r["created_at"],
        "started_at": r.get("started_at"),
        "stopped_at": r.get("stopped_at"),
        "current_equity": r.get("current_equity"),
        "realized_pnl": r.get("realized_pnl"),
        "num_orders": r.get("num_orders") or 0,
        "num_fills": r.get("num_fills") or 0,
    }
