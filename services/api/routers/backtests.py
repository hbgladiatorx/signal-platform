"""Backtest API endpoints.

Endpoints:
  POST   /backtests                  — create + enqueue a backtest
  GET    /backtests                  — list current user's backtests
  GET    /backtests/{id}             — one backtest header
  GET    /backtests/{id}/trades      — closed round trips
  GET    /backtests/{id}/equity      — equity curve

All endpoints require authentication via the existing Auth0 JWT flow.
User scoping is enforced server-side: each request resolves the JWT's
'sub' claim to a row in `users` and writes/reads only that user's data.

POST flow:
  1. Validate strategy_name exists in the registry
  2. Validate params against the strategy's PARAMS_MODEL (returns 422 with
     pydantic validation errors)
  3. Validate every symbol exists in the instruments table (returns 422)
  4. Validate bar_resolution against the known cagg set (returns 400)
  5. INSERT into backtests with status='pending'
  6. After the DB transaction commits, LPUSH the new id onto backtest:jobs
  7. Return the new id + status='pending'

If step 6 fails (Redis unavailable), the backtest stays in 'pending' status
indefinitely. A maintenance job could enqueue stuck pendings; for Phase 2
we accept this as a known caveat.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.backtest.persistence import (
    create_backtest,
    list_backtests_for_user,
    load_backtest,
    load_backtest_equity,
    load_backtest_trades,
)
from packages.data.messagebus import QUEUE_BACKTEST_JOBS
from packages.analysis.narrate import generate_narrative
from packages.analysis.tweak_advisor import suggest_param_tweaks
from starlette.concurrency import run_in_threadpool
from services.api.deps import (
    CurrentUserRecord,
    get_current_user_record,
    get_db_session,
)
from services.api.routers.strategies import get_strategy_registry
from services.api.certify_payload import build_certify_request
from services.api.routers.certify import (
    CertResponse,
    CertifyRequest,
    _require_signing_or_503,
    certify_submission,
)
from packages.data.user_strategies import get_user_strategy_by_name
from packages.strategy.graph_intent import graph_bar_resolution, graph_symbol
from packages.strategy.loader import StrategyLoadError
from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy


log = logging.getLogger(__name__)
router = APIRouter(prefix="/backtests", tags=["backtests"])


BarResolution = Literal["1m", "5m", "15m", "1h", "4h", "1d"]


# ============================================================
# Redis client (lazy, per-process)
# ============================================================
_redis_client: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


# ============================================================
# Request / response models
# ============================================================
class CreateBacktestRequest(BaseModel):
    strategy_name: str = Field(..., description="Name from GET /strategies")
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(..., min_length=1)
    bar_resolution: BarResolution = Field(default="1h")
    starting_cash: Decimal = Field(default=Decimal("10000"), gt=0)
    fee_rate_bps: int = Field(default=10, ge=0, le=1000)
    slippage_bps: int = Field(default=5, ge=0, le=1000)
    # Optional inclusive date window. Both NULL = full history (default
    # in-sample run); set both to run a bounded window, e.g. a held-out
    # out-of-sample segment. The worker filters bars to this range.
    window_start: datetime | None = Field(default=None)
    window_end: datetime | None = Field(default=None)

    @model_validator(mode="after")
    def _check_window(self) -> "CreateBacktestRequest":
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_start >= self.window_end
        ):
            raise ValueError("window_start must be strictly before window_end")
        return self


class CreateBacktestResponse(BaseModel):
    id: UUID
    status: str


class BacktestSummary(BaseModel):
    """Subset of backtests row suitable for list views."""

    id: UUID
    strategy_name: str
    symbols: list[str]
    bar_resolution: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    # Sample-size info for showing "Period tested" in the list
    bars_start: datetime | None = None
    bars_end: datetime | None = None
    num_bars: int | None = None
    # Performance metrics
    total_return_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    num_closed_trades: int | None = None
    win_rate_pct: float | None = None
    profit_factor: float | None = None


class BacktestDetail(BaseModel):
    """Full backtest header for detail views."""

    id: UUID
    strategy_name: str
    params_json: dict[str, Any]
    symbols: list[str]
    bar_resolution: str
    bars_start: datetime | None = None
    bars_end: datetime | None = None
    num_bars: int | None = None
    starting_cash: Decimal
    fee_rate_bps: int
    slippage_bps: int
    status: str
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    # Summary metrics
    total_return_pct: float | None = None
    annualized_return_pct: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float | None = None
    calmar_ratio: float | None = None
    num_closed_trades: int | None = None
    num_open_trades: int | None = None
    win_rate_pct: float | None = None
    profit_factor: float | None = None
    # Performance attribution (the "why"): per-symbol / per-signal P&L
    # decomposition and signal fire/block frequency. Stored verbatim as the
    # JSON shape produced by attribution_to_dict(). None for runs with no
    # closed trades or completed before attribution was added.
    attribution: dict[str, Any] | None = None
    # Signal-edge ML model (Phase 3): in-sample logistic fit over the
    # feature/label store — which signals predict profitable trades. Verbatim
    # model_to_dict() shape. None for runs with nothing to learn / pre-Phase-3.
    ml_model: dict[str, Any] | None = None
    # Deterministic analysis (the "what worked / why / what to fix"): verdict,
    # 0-100 score, derived metrics, and ranked findings. The optional LLM
    # narrative lives under analysis["narrative"]. analyze_backtest() shape.
    # None for runs completed before this was added.
    analysis: dict[str, Any] | None = None


class TradeRow(BaseModel):
    symbol: str
    side: str
    entry_ts: datetime
    exit_ts: datetime
    entry_avg_price: Decimal
    exit_avg_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    duration_seconds: float
    num_fills: int


class EquityPointRow(BaseModel):
    ts: datetime
    cash: Decimal
    positions_value: Decimal
    total_equity: Decimal


# ============================================================
# Validation helpers
# ============================================================
async def _validate_symbols(
    session: AsyncSession,
    symbols: list[str],
) -> None:
    """422 if any symbol isn't in instruments."""
    if not symbols:
        return
    result = await session.execute(
        text(
            "SELECT canonical_symbol FROM instruments "
            "WHERE canonical_symbol = ANY(:symbols)"
        ),
        {"symbols": symbols},
    )
    found = {row[0] for row in result.all()}
    missing = [s for s in symbols if s not in found]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": "Unknown symbol(s)",
                "missing": missing,
            },
        )


# ============================================================
# Endpoints
# ============================================================
@router.post("", response_model=CreateBacktestResponse, status_code=201)
async def create_new_backtest(
    req: CreateBacktestRequest,
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> CreateBacktestResponse:
    """Create + enqueue a new backtest."""
    # Single-symbol contract (validation-time block, before any work): compiled
    # strategies run on ONE symbol — their on_init raises on more than one, as
    # they have no capital-allocation model across a universe yet. Refuse
    # multi-symbol at acceptance with a clear message rather than queueing a run
    # that fails in the worker. The system no longer advises or offers
    # "add symbols"/UNIVERSE, so this only guards direct API callers. Lifting it
    # is future scope (real portfolio support).
    if len(req.symbols) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "msg": (
                    "This strategy runs on one symbol. Multi-symbol and "
                    "full-universe backtests aren't supported yet — run one "
                    "ticker at a time. To get more trades, extend the date "
                    "range or use a lower timeframe."
                ),
                "symbols": req.symbols,
            },
        )

    # Resolve strategy: registry first, then this user's user_strategies
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
            detail={
                "msg": f"Strategy {req.strategy_name!r} failed to compile",
                "error": str(e),
            },
        )
    strategy_cls = resolved.cls

    # Graph is the source of truth: if this is a graph-built user strategy, the
    # request's symbol/timeframe must match what the user wired on the canvas. A
    # mismatch is rejected — never silently honored — so the canvas and the
    # execution can't disagree. (Built-in / raw-code strategies have no graph and
    # are unaffected.)
    if resolved.source == "user":
        srow = await get_user_strategy_by_name(
            session, user_id=user.id, name=req.strategy_name
        )
        graph = (srow or {}).get("graph_json")
        g_sym = graph_symbol(graph)

        # Compare tickers venue-insensitively: the graph stores a human ticker
        # ("SPY") while the execution symbol is canonical ("SPY@ALPACA"). They
        # name the same instrument, so match on the ticker before the "@".
        def _ticker(s: str) -> str:
            return s.split("@", 1)[0].strip().upper()

        if g_sym and req.symbols and _ticker(req.symbols[0]) != _ticker(g_sym):
            raise HTTPException(
                status_code=422,
                detail={
                    "msg": (
                        f"This strategy's graph is wired for {g_sym}, but the "
                        f"backtest requested {req.symbols[0]}. The graph is the "
                        f"source of truth — change the symbol on the canvas to run "
                        f"a different ticker."
                    ),
                    "graph_symbol": g_sym,
                    "requested": req.symbols,
                },
            )
        g_tf = graph_bar_resolution(graph)
        if g_tf and req.bar_resolution.lower() != g_tf:
            raise HTTPException(
                status_code=422,
                detail={
                    "msg": (
                        f"This strategy's graph is set to the {g_tf} timeframe, "
                        f"but the backtest requested {req.bar_resolution}. The "
                        f"graph is the source of truth — change the timeframe on "
                        f"the canvas."
                    ),
                    "graph_timeframe": g_tf,
                    "requested": req.bar_resolution,
                },
            )

    # Validate params against the strategy's PARAMS_MODEL
    try:
        validated_params = strategy_cls.PARAMS_MODEL(**req.params)
    except ValidationError as e:
        # Use e.json() (always JSON-safe) rather than e.errors() (which can
        # contain raw ValueError instances in `ctx` when a model_validator
        # raises one — those aren't JSON-serializable).
        import json as _json
        raise HTTPException(
            status_code=422,
            detail={"msg": "Invalid params", "errors": _json.loads(e.json())},
        )

    # Validate symbols exist
    await _validate_symbols(session, req.symbols)

    # Insert in DB (session_scope commits at the end of the request)
    backtest_id = await create_backtest(
        session,
        user_id=user.id,
        org_id=user.org_id,
        strategy_name=req.strategy_name,
        params_json=validated_params.model_dump(),
        symbols=req.symbols,
        bar_resolution=req.bar_resolution,
        starting_cash=req.starting_cash,
        fee_rate_bps=req.fee_rate_bps,
        slippage_bps=req.slippage_bps,
        window_start=req.window_start,
        window_end=req.window_end,
    )

    # Flush so the row is visible to the worker once we push.
    await session.flush()
    await session.commit()

    # AFTER the commit, push to Redis. If this fails, the row stays pending
    # and a maintenance job can pick it up later.
    try:
        r = await _get_redis()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(backtest_id))
    except Exception as e:
        log.error(
            "backtests.enqueue_failed backtest_id=%s err=%s",
            backtest_id, e,
        )
        # Still return 201 — the row exists, just not enqueued.

    return CreateBacktestResponse(id=backtest_id, status="pending")


@router.get("", response_model=list[BacktestSummary])
async def list_my_backtests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[BacktestSummary]:
    """List backtests owned by the current user, most-recent first."""
    rows = await list_backtests_for_user(session, user.id, limit=limit, offset=offset)
    return [
        BacktestSummary(
            id=r["id"],
            strategy_name=r["strategy_name"],
            symbols=list(r["symbols"]),
            bar_resolution=r["bar_resolution"],
            status=r["status"],
            created_at=r["created_at"],
            completed_at=r.get("completed_at"),
            duration_seconds=float(r["duration_seconds"]) if r.get("duration_seconds") is not None else None,
            # Sample-size info — uses .get() so this works whether or not
            # the persistence layer's SELECT includes these columns.
            bars_start=r.get("bars_start"),
            bars_end=r.get("bars_end"),
            num_bars=r.get("num_bars"),
            total_return_pct=float(r["total_return_pct"]) if r.get("total_return_pct") is not None else None,
            sharpe_ratio=float(r["sharpe_ratio"]) if r.get("sharpe_ratio") is not None else None,
            max_drawdown_pct=float(r["max_drawdown_pct"]) if r.get("max_drawdown_pct") is not None else None,
            num_closed_trades=r.get("num_closed_trades"),
            win_rate_pct=float(r["win_rate_pct"]) if r.get("win_rate_pct") is not None else None,
            profit_factor=float(r["profit_factor"]) if r.get("profit_factor") is not None else None,
        )
        for r in rows
    ]


async def _load_my_backtest_or_404(
    session: AsyncSession,
    backtest_id: UUID,
    user: CurrentUserRecord,
) -> dict[str, Any]:
    """Load a backtest header, enforcing ownership. 404 if not yours."""
    row = await load_backtest(session, backtest_id)
    if row is None:
        raise HTTPException(404, "Backtest not found")
    # Note: we deliberately return 404 (not 403) when ownership fails to
    # avoid revealing existence to non-owners.
    if row["user_id"] != user.id:
        raise HTTPException(404, "Backtest not found")
    return row


def _opt_float(v: Any) -> float | None:
    return float(v) if v is not None else None


@router.get("/{backtest_id}", response_model=BacktestDetail)
async def get_one_backtest(
    backtest_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> BacktestDetail:
    row = await _load_my_backtest_or_404(session, backtest_id, user)
    return BacktestDetail(
        id=row["id"],
        strategy_name=row["strategy_name"],
        params_json=row["params_json"] or {},
        symbols=list(row["symbols"]),
        bar_resolution=row["bar_resolution"],
        bars_start=row.get("bars_start"),
        bars_end=row.get("bars_end"),
        num_bars=row.get("num_bars"),
        starting_cash=row["starting_cash"],
        fee_rate_bps=row["fee_rate_bps"],
        slippage_bps=row["slippage_bps"],
        status=row["status"],
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        duration_seconds=_opt_float(row.get("duration_seconds")),
        total_return_pct=_opt_float(row.get("total_return_pct")),
        annualized_return_pct=_opt_float(row.get("annualized_return_pct")),
        sharpe_ratio=_opt_float(row.get("sharpe_ratio")),
        sortino_ratio=_opt_float(row.get("sortino_ratio")),
        max_drawdown_pct=_opt_float(row.get("max_drawdown_pct")),
        calmar_ratio=_opt_float(row.get("calmar_ratio")),
        num_closed_trades=row.get("num_closed_trades"),
        num_open_trades=row.get("num_open_trades"),
        win_rate_pct=_opt_float(row.get("win_rate_pct")),
        profit_factor=_opt_float(row.get("profit_factor")),
        attribution=row.get("attribution_json"),
        ml_model=row.get("ml_model_json"),
        analysis=row.get("analysis_json"),
    )


@router.get("/{backtest_id}/trades", response_model=list[TradeRow])
async def get_backtest_trades(
    backtest_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[TradeRow]:
    # Ownership check first
    await _load_my_backtest_or_404(session, backtest_id, user)
    rows = await load_backtest_trades(session, backtest_id)
    return [
        TradeRow(
            symbol=r["symbol"],
            side=r["side"],
            entry_ts=r["entry_ts"],
            exit_ts=r["exit_ts"],
            entry_avg_price=r["entry_avg_price"],
            exit_avg_price=r["exit_avg_price"],
            quantity=r["quantity"],
            gross_pnl=r["gross_pnl"],
            fees=r["fees"],
            net_pnl=r["net_pnl"],
            duration_seconds=float(r["duration_seconds"]),
            num_fills=r["num_fills"],
        )
        for r in rows
    ]


@router.get("/{backtest_id}/equity", response_model=list[EquityPointRow])
async def get_backtest_equity(
    backtest_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> list[EquityPointRow]:
    await _load_my_backtest_or_404(session, backtest_id, user)
    rows = await load_backtest_equity(session, backtest_id)
    return [
        EquityPointRow(
            ts=r["ts"],
            cash=r["cash"],
            positions_value=r["positions_value"],
            total_equity=r["total_equity"],
        )
        for r in rows
    ]


class CertifyBacktestRequest(BaseModel):
    """Certify a backtest the user already ran.

    The evidence (equity curve WITH per-bar exposure) is sourced server-side from
    the backtest, so the exposure-aware integrity path engages automatically. Only
    the honest declaration is required from the caller.
    """

    model_config = ConfigDict(extra="forbid")

    declared_trials: int = Field(
        ..., ge=1,
        description="Configs/variants you tried to reach this strategy (>=1; declare "
                    "1 if no search was run). Stamped self_declared and fed verbatim "
                    "to the deflation — the same bar as every other certify path.",
    )
    cost_bps: float | None = Field(
        default=None, ge=0,
        description="Round-trip cost in bps. Defaults to the backtest's own "
                    "fee + slippage so the cert matches what was actually simulated.",
    )
    declared_grid_size: int | None = Field(
        default=None, ge=1,
        description="Declared parameter-grid size, if this came from a grid/search; "
                    "raises the provable trial floor.",
    )


@router.post("/{backtest_id}/certify", response_model=CertResponse)
async def certify_backtest(
    backtest_id: UUID = Path(...),
    body: CertifyBacktestRequest = ...,  # noqa: B008
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> CertResponse:
    """Certify a backtest the user owns: source its equity-with-exposure, build the
    evidence (so the exposure-aware path engages), and run the SAME referee engine
    path as POST /referee/certify (intake -> certify -> signed report), persisting
    the signed verdict for later retrieval by verification_id.

    Nothing about grading or signing is reimplemented or loosened here — this only
    opens the door to the existing engine for a backtest the user already ran.
    """
    # Refuse before any work if the production signing guard isn't satisfied:
    # an unsigned/insecure cert must never be issued (same rule as every path).
    _require_signing_or_503()

    row = await _load_my_backtest_or_404(session, backtest_id, user)
    if row["status"] != "completed":
        raise HTTPException(
            status_code=422,
            detail={"msg": "Only a completed backtest can be certified.",
                    "status": row["status"]},
        )

    equity_rows = await load_backtest_equity(session, backtest_id)
    # Honest cost: default to the backtest's own simulated round-trip cost.
    cost_bps = (body.cost_bps if body.cost_bps is not None
                else float(row["fee_rate_bps"] + row["slippage_bps"]))

    payload = build_certify_request(
        equity_rows, declared_trials=body.declared_trials, cost_bps=cost_bps,
    )
    if payload is None:
        raise HTTPException(
            status_code=422,
            detail={"msg": "This backtest has no equity curve to certify."},
        )

    # Hand the evidence to the unchanged certify engine path (signing guard,
    # grading, persistence, response shaping all reused).
    certify_req = CertifyRequest(
        csv_text=payload["csv_text"],
        declared_trials=payload["declared_trials"],
        cost_bps=payload["cost_bps"],
        fmt="equity_curve",
        declared_grid_size=body.declared_grid_size,
    )
    return await certify_submission(req=certify_req, user=user)


class NarrativeResponse(BaseModel):
    ok: bool
    # The generated prose (markdown). Present iff ok. Also persisted into
    # analysis_json["narrative"] so the detail view shows it without re-asking.
    narrative: str | None = None
    # User-readable reason when ok is False (e.g. credits exhausted). The
    # deterministic findings remain available regardless.
    error: str | None = None


@router.post("/{backtest_id}/narrative", response_model=NarrativeResponse)
async def generate_backtest_narrative(
    backtest_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> NarrativeResponse:
    """Generate (and cache) an LLM narrative over the deterministic analysis.

    On-demand and best-effort: if the analysis is missing the call 400s; if the
    LLM is unavailable (no key / no credit) it returns ok=False with a reason
    and the UI falls back to the structured findings. A successful narrative is
    persisted into analysis_json["narrative"].
    """
    row = await _load_my_backtest_or_404(session, backtest_id, user)
    analysis = row.get("analysis_json")
    if not analysis:
        raise HTTPException(
            400,
            "No analysis available for this backtest yet (it may predate the "
            "analysis feature or have no closed trades).",
        )

    result = await run_in_threadpool(
        generate_narrative, analysis, row.get("strategy_name")
    )
    if not result.ok:
        return NarrativeResponse(ok=False, error=result.error)

    # Persist the narrative into the analysis blob so it survives reloads.
    merged = {**analysis, "narrative": result.narrative}
    await session.execute(
        text(
            "UPDATE backtests SET analysis_json = CAST(:a AS JSONB) WHERE id = :id"
        ),
        {"a": json.dumps(merged), "id": backtest_id},
    )
    await session.commit()
    return NarrativeResponse(ok=True, narrative=result.narrative)


class SuggestTweaksRequest(BaseModel):
    # The strategy's current builder graph, sent by the frontend (which already
    # has it loaded). The advisor targets real node ids/fields so the UI can
    # patch the graph in place and re-backtest. Shape: {"nodes":[...],"edges":[...]}.
    graph_json: dict[str, Any] | None = Field(default=None)


class ParamTweak(BaseModel):
    node_id: str
    node_label: str | None = None
    node_type: str | None = None
    field: str
    current: Any = None
    suggested: Any
    rationale: str = ""


class SuggestTweaksResponse(BaseModel):
    ok: bool
    summary: str = ""
    tweaks: list[ParamTweak] = []
    error: str | None = None


@router.post("/{backtest_id}/suggest-tweaks", response_model=SuggestTweaksResponse)
async def suggest_backtest_tweaks(
    body: SuggestTweaksRequest,
    backtest_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUserRecord = Depends(get_current_user_record),
) -> SuggestTweaksResponse:
    """AI: find specific parameters worth tweaking, tied to the strategy's graph.

    Given this backtest's deterministic analysis + the strategy's node graph,
    Claude proposes editable {node, field, current, suggested} tweaks the user
    can adjust and re-backtest. Best-effort: ok=False (with a reason) when the
    LLM is unavailable or the strategy has no editable graph.
    """
    row = await _load_my_backtest_or_404(session, backtest_id, user)
    analysis = row.get("analysis_json")
    if not analysis:
        raise HTTPException(
            400,
            "No analysis available for this backtest yet (it may predate the "
            "analysis feature or have no closed trades).",
        )

    result = await run_in_threadpool(
        suggest_param_tweaks, analysis, body.graph_json, row.get("strategy_name")
    )
    if not result.ok:
        return SuggestTweaksResponse(ok=False, error=result.error, summary=result.summary)
    return SuggestTweaksResponse(
        ok=True,
        summary=result.summary,
        tweaks=[ParamTweak(**t) for t in result.tweaks],
    )
