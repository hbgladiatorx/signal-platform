"""Bayn Copilot tool schemas + server-side dispatch.

TOOL_SCHEMAS is the corrected tool list handed to Anthropic. Each tool maps to
real platform machinery; dispatch_tool() executes it against the DB + workers,
applying the copilot's own smart defaults (last 2 years, $25k, 5/3 bps, the
stocks universe) at this layer so the underlying endpoints keep their defaults
for every other caller.

Reality the tools honour that the original spec missed:
  * backtests / OOS / forward run on background workers — we enqueue, then
    briefly poll; if a run is still going we return status="running".
  * run_oos_test is a walk-forward (the platform's held-out-history test); we
    synthesize a sane param grid + window sizing from the strategy.
  * there is no standalone deploy endpoint — deploying = starting a (paper or
    live) trading session, with the mode decided by the credential's venue.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.backtest.persistence import create_backtest, load_backtest
from packages.backtest.walkforward_persistence import create_walkforward
from packages.data.db import get_engine
from packages.data.messagebus import (
    QUEUE_BACKTEST_JOBS,
    QUEUE_PAPER_CONTROL,
    QUEUE_WALKFORWARD_JOBS,
)
from packages.data.platform_credentials import PLATFORM_USER_ID
from packages.data.user_strategies import (
    create_user_strategy,
    get_user_strategy,
    get_user_strategy_by_name,
    set_strategy_lifecycle_milestone,
    update_user_strategy,
)
from packages.livetrade import persistence as P
from packages.strategy.graph_compiler import compile_graph_to_source
from packages.strategy.graph_planner import plan_graph_from_nl
from packages.strategy.llm_translator import translate_nl_to_strategy
from packages.strategy.loader import StrategyLoadError
from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy
from packages.strategy.validator import validate_strategy_source

from packages.copilot.state import STAGES, compute_strategy_state

log = logging.getLogger(__name__)


# ============================================================
# Copilot smart defaults (applied at the tool layer)
# ============================================================
BACKTEST_DEFAULT_CASH = Decimal("25000")
BACKTEST_DEFAULT_FEE_BPS = 5
BACKTEST_DEFAULT_SLIPPAGE_BPS = 3
BACKTEST_DEFAULT_LOOKBACK_DAYS = 730  # "last 2 years"
DEFAULT_BAR_RESOLUTION = "1d"

# The stocks universe the spec's symbols='UNIVERSE' option expands to
# (mirrors scripts/universe_50.txt). Filtered to instruments that actually
# exist before a run.
UNIVERSE_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "NFLX", "AMD",
    "JPM", "V", "MA", "UNH", "JNJ", "WMT", "PG", "HD", "BAC", "XOM",
    "CVX", "KO", "PEP", "COST", "DIS", "ADBE", "CRM", "INTC", "CSCO", "ORCL",
    "QCOM", "TXN", "PFE", "MRK", "ABBV", "NKE", "MCD", "T", "VZ", "GS",
    "CAT", "BA", "GE", "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "GLD",
]

# How long a tool call will wait for an async run before returning "running".
# Kept well under the gunicorn worker timeout (120s).
POLL_TIMEOUT_SECONDS = int(os.environ.get("COPILOT_POLL_SECONDS", "25"))
POLL_INTERVAL_SECONDS = 2

# Strategy asset_class (free text) -> paper-session AssetClass enum.
_ASSET_CLASS_TO_PAPER = {
    "stocks": "equity",
    "stock": "equity",
    "equity": "equity",
    "equities": "equity",
    "options": "option",
    "option": "option",
    "crypto": "crypto_spot",
    "crypto_spot": "crypto_spot",
}


class ToolError(Exception):
    """A user-surfaceable tool failure. dispatch wraps it as {ok: false, error}."""


# ============================================================
# Tool schemas (the corrected spec list)
# ============================================================
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_strategy_state",
        "description": (
            "Return the current lifecycle stage, the latest backtest summary, "
            "OOS/forward progress, and which gates have passed for a strategy. "
            "Call this before acting on any existing strategy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"strategy_id": {"type": "string"}},
            "required": ["strategy_id"],
        },
    },
    {
        "name": "build_strategy",
        "description": (
            "Wire a new strategy onto the node canvas from a plain-English "
            "description. Produces the DATA -> INDICATOR -> LOGIC -> RISK -> "
            "SIGNAL graph, compiles + validates it, saves it, and returns a "
            "strategy_id in the draft stage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Plain-English strategy, e.g. 'Buy SPY when RSI drops below 30, exit above 50, 2% risk per trade'",
                },
                "asset_class": {
                    "type": "string",
                    "enum": ["stocks", "crypto", "options"],
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "edit_strategy_node",
        "description": (
            "Patch one node on an existing graph without rebuilding it, then "
            "recompile + revalidate. Use for tweaks like changing a stop, RSI "
            "period, timeframe, or position size. Note: prior backtest/OOS "
            "results become stale after an edit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "node": {
                    "type": "string",
                    "enum": ["data", "indicator", "logic", "risk", "signal"],
                },
                "change": {
                    "type": "string",
                    "description": "Plain-English change, e.g. 'set stop to 4 ATR' or 'loosen RSI entry to 35'",
                },
            },
            "required": ["strategy_id", "node", "change"],
        },
    },
    {
        "name": "run_backtest",
        "description": (
            "Run a backtest against historical data. Runs on a background "
            "worker; the result tells you whether it completed in time or is "
            "still running. Omitted optional fields use smart defaults: last 2 "
            "years, $25,000 capital, 5 bps commission, 3 bps slippage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tickers, or omit to reuse the strategy's last symbols. Pass ['UNIVERSE'] to run the full stocks universe.",
                },
                "start_date": {"type": "string", "description": "ISO date; defaults to 2 years ago."},
                "end_date": {"type": "string", "description": "ISO date; defaults to now."},
                "starting_capital": {"type": "number"},
                "commission_bps": {"type": "number"},
                "slippage_bps": {"type": "number"},
            },
            "required": ["strategy_id"],
        },
    },
    {
        "name": "get_backtest_analysis",
        "description": (
            "Return full metrics plus per-symbol and per-signal attribution for "
            "a backtest. If the run is still in progress, returns its status "
            "instead. Use this to write the plain-English verdict and to "
            "diagnose failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"backtest_id": {"type": "string"}},
            "required": ["backtest_id"],
        },
    },
    {
        "name": "run_oos_test",
        "description": (
            "Run the out-of-sample test (a walk-forward): re-tune and re-test "
            "the strategy on held-out slices of history it was never tuned on. "
            "Advances a backtested strategy to oos_passed if it holds up. Needs "
            "at least one completed backtest first (for symbols + timeframe)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"strategy_id": {"type": "string"}},
            "required": ["strategy_id"],
        },
    },
    {
        "name": "start_forward_test",
        "description": (
            "Begin forward testing against live bars with paper (simulated) "
            "fills. Advances oos_passed -> forward."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"strategy_id": {"type": "string"}},
            "required": ["strategy_id"],
        },
    },
    {
        "name": "promote_strategy",
        "description": (
            "Promote a forward-tested strategy to deployable. Requires explicit "
            "user confirmation in their latest message (pass user_confirmed=true)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
            },
            "required": ["strategy_id", "user_confirmed"],
        },
    },
    {
        "name": "deploy_strategy",
        "description": (
            "Deploy a deployable strategy by starting a trading session. "
            "mode 'paper' runs on a paper account (allowed on request). mode "
            "'live' trades REAL money and requires user_confirmed=true plus an "
            "available live trading credential."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["paper", "live"]},
                "user_confirmed": {"type": "boolean"},
            },
            "required": ["strategy_id", "mode"],
        },
    },
    {
        "name": "submit_to_bayn",
        "description": (
            "Submit a Bayn-eligible (live-deployed) strategy to the desk for "
            "review. Requires user confirmation (user_confirmed=true)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
            },
            "required": ["strategy_id", "user_confirmed"],
        },
    },
]


# ============================================================
# Redis (lazy, per-process)
# ============================================================
_redis_client: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


# ============================================================
# Small helpers
# ============================================================
async def _load_strategy_or_raise(
    session: AsyncSession, user_id: UUID, strategy_id_str: str
) -> dict[str, Any]:
    try:
        sid = UUID(strategy_id_str)
    except (ValueError, TypeError):
        raise ToolError(f"'{strategy_id_str}' is not a valid strategy id.")
    row = await get_user_strategy(session, strategy_id=sid, user_id=user_id)
    if row is None:
        raise ToolError("That strategy doesn't exist (or isn't yours).")
    return row


async def _filter_known_symbols(session: AsyncSession, symbols: list[str]) -> list[str]:
    """Resolve user-supplied tickers to full canonical symbols, dropping any
    that don't exist.

    The whole downstream pipeline (bar loading, instrument meta, live runner)
    keys on the *full* ``canonical_symbol`` — e.g. ``SPY@ALPACA`` or
    ``BTC-USD@BINANCEUS``. Users (and the copilot's UNIVERSE list) speak bare
    tickers (``SPY``) or crypto bases (``BTC``), so we accept any of: the full
    canonical symbol, the venue-native symbol, or the base asset, and return the
    canonical form. Request order is preserved and duplicates collapsed; options
    are matched only by their explicit canonical symbol.
    """
    if not symbols:
        return []
    tokens = [s.strip().upper() for s in symbols if s and s.strip()]
    if not tokens:
        return []
    res = await session.execute(
        text(
            "SELECT canonical_symbol, native_symbol, base, asset_class "
            "FROM instruments "
            "WHERE active AND ("
            "  upper(canonical_symbol) = ANY(:t)"
            "  OR (asset_class <> 'option' AND ("
            "    upper(native_symbol) = ANY(:t) OR upper(base) = ANY(:t)))"
            ")"
        ),
        {"t": tokens},
    )
    # Index every candidate by each alias it answers to (canonical / native /
    # base), so a bare ticker or base finds its row.
    by_alias: dict[str, list[dict[str, Any]]] = {}
    for row in res.mappings():
        r = dict(row)
        aliases = {
            (r["canonical_symbol"] or "").upper(),
            (r["native_symbol"] or "").upper(),
            (r["base"] or "").upper(),
        }
        for alias in aliases:
            if alias:
                by_alias.setdefault(alias, []).append(r)

    def _pick(cands: list[dict[str, Any]]) -> str:
        # Deterministic when a token is ambiguous (e.g. base 'BTC' -> BTC-USD /
        # BTC-USDT): prefer equities, then the alphabetically-first canonical,
        # which places '-USD@' before '-USDT@'.
        best = sorted(
            cands,
            key=lambda c: (
                0 if c["asset_class"] == "equity" else 1,
                c["canonical_symbol"],
            ),
        )[0]
        return best["canonical_symbol"]

    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        cands = by_alias.get(tok)
        if not cands:
            continue
        canonical = _pick(cands)
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out


async def _resolve_symbols(
    session: AsyncSession, user_id: UUID, strategy_name: str, requested: Optional[list[str]]
) -> list[str]:
    """Resolve the symbol list for a run: explicit list, 'UNIVERSE', or the
    strategy's last backtest symbols. Filters to instruments that exist."""
    if requested:
        if any(s.upper() == "UNIVERSE" for s in requested):
            candidates = UNIVERSE_SYMBOLS
        else:
            candidates = [s.upper() for s in requested]
        known = await _filter_known_symbols(session, candidates)
        if not known:
            raise ToolError(
                "None of those symbols exist in the platform's instrument data."
            )
        return known
    # Fall back to the last backtest's symbols.
    res = await session.execute(
        text(
            "SELECT symbols FROM backtests WHERE user_id = :uid AND strategy_name = :name "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"uid": user_id, "name": strategy_name},
    )
    row = res.first()
    if row and row[0]:
        return list(row[0])
    raise ToolError(
        "No symbols given and this strategy has never been backtested — "
        "tell me which tickers to run (or say 'the universe')."
    )


async def _latest_backtest_meta(
    session: AsyncSession, user_id: UUID, strategy_name: str
) -> Optional[dict[str, Any]]:
    res = await session.execute(
        text(
            "SELECT symbols, bar_resolution, status FROM backtests "
            "WHERE user_id = :uid AND strategy_name = :name "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"uid": user_id, "name": strategy_name},
    )
    m = res.mappings().first()
    return dict(m) if m else None


# Valid bar resolutions a run can execute at (mirrors
# livetrade.bars.RESOLUTION_TABLE).
_VALID_BAR_RESOLUTIONS = {"1m", "5m", "15m", "1h", "4h", "1d"}


def _graph_bar_resolution(graph: Optional[dict[str, Any]]) -> Optional[str]:
    """Pull the timeframe the user set on the graph's data (price) node.

    The graph is the source of truth for a strategy's timeframe — the user edits
    it directly (e.g. "make it 5m"), and that edit is saved to the price node's
    ``data.timeframe``. Runs must honor it; otherwise a timeframe change silently
    has no effect because the run inherits the *previous* backtest's resolution.
    Returns a valid bar resolution, or None if the graph has no usable one.
    """
    if not graph:
        return None
    for node in graph.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "price" or node.get("category") == "data":
            tf = ((node.get("data") or {}).get("timeframe") or "").strip().lower()
            if tf in _VALID_BAR_RESOLUTIONS:
                return tf
    return None


def _resolve_and_validate_params(cls: Any, params: dict[str, Any]) -> dict[str, Any]:
    from pydantic import ValidationError

    try:
        return cls.PARAMS_MODEL(**(params or {})).model_dump()
    except ValidationError as e:
        import json as _json

        raise ToolError(f"Strategy params are invalid: {_json.loads(e.json())}")


async def _poll_until_terminal(table: str, row_id: UUID, terminal: set[str]) -> str:
    """Poll a job row's status on fresh connections (READ COMMITTED sees worker
    commits) until terminal or timeout. Returns the last-seen status."""
    engine = get_engine()
    waited = 0
    status = "pending"
    while waited <= POLL_TIMEOUT_SECONDS:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(f"SELECT status FROM {table} WHERE id = :id"),  # noqa: S608 (table is a literal)
                {"id": row_id},
            )
            r = res.first()
            status = r[0] if r else status
        if status in terminal:
            return status
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
    return status


def _build_param_grid(params_schema: dict[str, Any]) -> dict[str, list[Any]]:
    """Synthesize a small walk-forward grid from a strategy's numeric params.

    Picks up to two integer/number params that have a default and brackets each
    with a low/current/high point so the walk-forward has something to select
    over. Falls back to a single-combo grid if nothing numeric is tunable.
    """
    props = (params_schema or {}).get("properties", {}) or {}
    grid: dict[str, list[Any]] = {}
    for name, spec in props.items():
        if len(grid) >= 2:
            break
        if not isinstance(spec, dict):
            continue
        typ = spec.get("type")
        default = spec.get("default")
        if typ == "integer" and isinstance(default, int) and default > 1:
            lo = max(1, int(round(default * 0.6)))
            hi = int(round(default * 1.5))
            pts = sorted({lo, default, hi})
            if len(pts) >= 2:
                grid[name] = pts
        elif typ == "number" and isinstance(default, (int, float)) and default > 0:
            lo = round(default * 0.6, 4)
            hi = round(default * 1.5, 4)
            pts = sorted({lo, float(default), hi})
            if len(pts) >= 2:
                grid[name] = pts
    if grid:
        return grid
    # Fallback: a single-combo grid from the first param with any default, so
    # the walk-forward is still valid (non-empty lists) even with nothing to tune.
    for name, spec in props.items():
        if isinstance(spec, dict) and "default" in spec:
            return {name: [spec["default"]]}
    raise ToolError(
        "This strategy has no tunable parameters, so an out-of-sample walk-"
        "forward has nothing to select over. Add a parameter or skip OOS."
    )


# ============================================================
# Tool implementations
# ============================================================
async def _tool_get_strategy_state(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    return await compute_strategy_state(session, user_id=user.id, strategy_row=row)


async def _tool_build_strategy(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    description = inp["description"]
    asset_class = inp.get("asset_class") or "stocks"

    plan = plan_graph_from_nl(
        nl_description=description, asset_class_hint=asset_class, context_graph=None
    ).to_dict()
    if not plan.get("ok") or not plan.get("graph"):
        raise ToolError(
            f"Couldn't turn that into a node graph: {plan.get('error') or 'unknown error'}"
        )

    base_name = (plan.get("name") or "Strategy").strip()[:90] or "Strategy"
    name = base_name
    n = 2
    while await get_user_strategy_by_name(session, user_id=user.id, name=name) is not None:
        name = f"{base_name} {n}"
        n += 1

    # Prefer the deterministic graph compiler — it guarantees the code matches
    # the planned graph (every entry/exit/risk node honoured). When the graph
    # uses a node the compiler can't faithfully emit (e.g. a `crossover`
    # primitive), it returns ok=False; we then fall back to the LLM translator,
    # exactly as the /user-strategies/translate endpoint does. Without this
    # fallback the copilot dead-ends on any strategy the compiler doesn't cover.
    source_code: str | None = None
    class_name: str | None = None
    params_schema: Any = None
    build_note: str | None = None

    compiled = compile_graph_to_source(
        name=name, asset_class=asset_class, graph=plan["graph"]
    )
    if compiled.ok and compiled.source_code:
        validation = validate_strategy_source(compiled.source_code)
        if validation.ok:
            source_code = compiled.source_code
            class_name = validation.class_name or compiled.class_name
            params_schema = validation.params_schema
        else:
            log.info(
                "copilot.build compiled_invalid reason=%s", compiled.reason
            )
    else:
        log.info("copilot.build compile_fallback reason=%s", compiled.reason)

    if source_code is None:
        # LLM fallback: translate the NL description straight to source.
        llm = translate_nl_to_strategy(nl_description=description)
        if not llm.ok or not llm.source_code:
            raise ToolError(
                f"The graph didn't compile ({compiled.reason}) and the LLM "
                f"fallback also failed: {llm.error or 'unknown error'}"
            )
        validation = validate_strategy_source(llm.source_code)
        if not validation.ok:
            errs = [e.as_dict() for e in validation.errors][:3]
            raise ToolError(f"The generated strategy failed validation: {errs}")
        source_code = llm.source_code
        class_name = validation.class_name or llm.class_name
        params_schema = validation.params_schema
        build_note = (
            "Built via the AI translator (the graph used a node the "
            "deterministic compiler doesn't cover yet)."
        )

    new_id = await create_user_strategy(
        session,
        user_id=user.id,
        org_id=user.org_id,
        name=name,
        description=description[:2000],
        nl_description=description[:4000],
        class_name=class_name,
        source_code=source_code,
        params_schema=params_schema,
        graph_json=plan["graph"],
        asset_class=asset_class,
    )
    await session.commit()
    result = {
        "ok": True,
        "strategy_id": str(new_id),
        "name": name,
        "stage": "draft",
        "plan": plan.get("plan", []),
        "assumptions": plan.get("assumptions", []),
    }
    if build_note:
        result["note"] = build_note
    return result


async def _tool_edit_strategy_node(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    graph = row.get("graph_json")
    if not graph:
        raise ToolError(
            "This strategy has no editable node graph (it was added as raw "
            "code), so I can't patch a single node. I can rebuild it instead."
        )
    asset_class = row.get("asset_class") or "stocks"
    node = inp["node"]
    change = inp["change"]

    plan = plan_graph_from_nl(
        nl_description=f"On the {node} node of this strategy: {change}",
        asset_class_hint=asset_class,
        context_graph=graph,
    ).to_dict()
    if not plan.get("ok") or not plan.get("graph"):
        raise ToolError(
            f"Couldn't apply that edit: {plan.get('error') or 'unknown error'}"
        )

    compiled = compile_graph_to_source(
        name=row["name"], asset_class=asset_class, graph=plan["graph"]
    )
    if not compiled.ok or not compiled.source_code:
        raise ToolError(f"The edited graph didn't compile: {compiled.reason}")

    validation = validate_strategy_source(compiled.source_code)
    if not validation.ok:
        errs = [e.as_dict() for e in validation.errors][:3]
        raise ToolError(f"The edit produced invalid code: {errs}")

    ok = await update_user_strategy(
        session,
        strategy_id=row["id"],
        user_id=user.id,
        class_name=validation.class_name or compiled.class_name,
        source_code=compiled.source_code,
        params_schema=validation.params_schema,
        graph_json=plan["graph"],
    )
    await session.commit()
    if not ok:
        raise ToolError("Couldn't save the edit.")
    return {
        "ok": True,
        "strategy_id": str(row["id"]),
        "node": node,
        "change": change,
        "note": "Edit applied. Any earlier backtest/OOS results are now stale — re-run them.",
    }


async def _tool_run_backtest(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, registry: dict[str, Any], **_: Any
) -> dict[str, Any]:
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    name = row["name"]

    # Resolve + validate the strategy compiles.
    try:
        resolved = await resolve_strategy(
            session, user_id=user.id, strategy_name=name, builtin_registry=registry
        )
    except StrategyNotFoundError:
        raise ToolError(f"Strategy {name!r} not found.")
    except StrategyLoadError as e:
        raise ToolError(f"Strategy {name!r} failed to compile: {e}")

    params = _resolve_and_validate_params(resolved.cls, {})
    symbols = await _resolve_symbols(session, user.id, name, inp.get("symbols"))

    # Window: explicit dates, else last 2 years.
    end = _parse_dt(inp.get("end_date")) or datetime.now(timezone.utc)
    start = _parse_dt(inp.get("start_date")) or (
        end - timedelta(days=BACKTEST_DEFAULT_LOOKBACK_DAYS)
    )

    cash = Decimal(str(inp["starting_capital"])) if inp.get("starting_capital") else BACKTEST_DEFAULT_CASH
    fee = int(inp["commission_bps"]) if inp.get("commission_bps") is not None else BACKTEST_DEFAULT_FEE_BPS
    slip = int(inp["slippage_bps"]) if inp.get("slippage_bps") is not None else BACKTEST_DEFAULT_SLIPPAGE_BPS

    # Timeframe priority: the graph the user edits is the source of truth, then
    # the last backtest's resolution, then the default. Reading from the graph
    # is what makes "switch to 5m" actually take effect — previously the run
    # inherited the prior backtest's resolution and silently ignored the edit.
    meta = await _latest_backtest_meta(session, user.id, name)
    bar_resolution = (
        _graph_bar_resolution(row.get("graph_json"))
        or (meta or {}).get("bar_resolution")
        or DEFAULT_BAR_RESOLUTION
    )

    backtest_id = await create_backtest(
        session,
        user_id=user.id,
        org_id=user.org_id,
        strategy_name=name,
        params_json=params,
        symbols=symbols,
        bar_resolution=bar_resolution,
        starting_cash=cash,
        fee_rate_bps=fee,
        slippage_bps=slip,
        window_start=start,
        window_end=end,
    )
    await session.commit()

    try:
        r = await _get_redis()
        await r.lpush(QUEUE_BACKTEST_JOBS, str(backtest_id))
    except Exception as e:  # noqa: BLE001
        log.error("copilot.backtest_enqueue_failed id=%s err=%s", backtest_id, e)
        return {
            "ok": True,
            "backtest_id": str(backtest_id),
            "status": "pending",
            "note": "Queued, but the job runner couldn't be reached — it may be delayed.",
        }

    status = await _poll_until_terminal("backtests", backtest_id, {"completed", "failed"})
    return {
        "ok": True,
        "backtest_id": str(backtest_id),
        "status": status,
        "symbols": symbols,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "note": (
            "Completed — call get_backtest_analysis for the verdict."
            if status == "completed"
            else "Still running on the worker — check get_backtest_analysis shortly."
            if status not in {"failed"}
            else "The run failed — call get_backtest_analysis for the error."
        ),
    }


async def _tool_get_backtest_analysis(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    try:
        bid = UUID(inp["backtest_id"])
    except (ValueError, TypeError):
        raise ToolError("That isn't a valid backtest id.")
    row = await load_backtest(session, bid)
    if row is None or row["user_id"] != user.id:
        raise ToolError("That backtest doesn't exist (or isn't yours).")

    status = row["status"]
    if status != "completed":
        return {
            "ok": True,
            "backtest_id": str(bid),
            "status": status,
            "error_message": row.get("error_message"),
            "note": "Not finished yet." if status in {"pending", "running"} else "Run did not complete.",
        }

    def _of(v: Any) -> Optional[float]:
        return float(v) if v is not None else None

    return {
        "ok": True,
        "backtest_id": str(bid),
        "status": "completed",
        "metrics": {
            "num_closed_trades": row.get("num_closed_trades"),
            "total_return_pct": _of(row.get("total_return_pct")),
            "annualized_return_pct": _of(row.get("annualized_return_pct")),
            "sharpe_ratio": _of(row.get("sharpe_ratio")),
            "sortino_ratio": _of(row.get("sortino_ratio")),
            "max_drawdown_pct": _of(row.get("max_drawdown_pct")),
            "calmar_ratio": _of(row.get("calmar_ratio")),
            "win_rate_pct": _of(row.get("win_rate_pct")),
            "profit_factor": _of(row.get("profit_factor")),
        },
        "trustworthy_sample": bool(
            row.get("num_closed_trades") is not None and row["num_closed_trades"] >= 30
        ),
        "attribution": row.get("attribution_json"),
        "analysis": row.get("analysis_json"),
    }


async def _tool_run_oos_test(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    name = row["name"]

    meta = await _latest_backtest_meta(session, user.id, name)
    if not meta or meta.get("status") != "completed":
        raise ToolError(
            "Run (and complete) a backtest first — the out-of-sample test reuses "
            "its symbols and timeframe."
        )
    symbols = list(meta["symbols"])
    bar_resolution = (
        _graph_bar_resolution(row.get("graph_json"))
        or meta.get("bar_resolution")
        or DEFAULT_BAR_RESOLUTION
    )
    param_grid = _build_param_grid(row.get("params_schema") or {})

    wf_id = uuid4()
    engine = get_engine()
    async with engine.begin() as conn:
        await create_walkforward(
            conn,
            walkforward_id=wf_id,
            user_id=user.id,
            strategy_name=name,
            symbols=symbols,
            bar_resolution=bar_resolution,
            starting_cash=BACKTEST_DEFAULT_CASH,
            fee_rate_bps=BACKTEST_DEFAULT_FEE_BPS,
            slippage_bps=BACKTEST_DEFAULT_SLIPPAGE_BPS,
            param_grid=param_grid,
            train_bars=750,
            test_bars=180,
            num_windows=4,
            selection_metric="sharpe",
        )

    try:
        r = await _get_redis()
        await r.lpush(QUEUE_WALKFORWARD_JOBS, str(wf_id))
    except Exception as e:  # noqa: BLE001
        log.error("copilot.oos_enqueue_failed id=%s err=%s", wf_id, e)

    status = await _poll_until_terminal("walkforwards", wf_id, {"completed", "failed"})
    result: dict[str, Any] = {"ok": True, "oos_id": str(wf_id), "status": status, "param_grid": param_grid}
    if status == "completed":
        res = await session.execute(
            text("SELECT avg_test_sharpe, avg_test_return_pct, overfit_drop FROM walkforwards WHERE id = :id"),
            {"id": wf_id},
        )
        m = res.mappings().first()
        if m:
            ats = m["avg_test_sharpe"]
            result["avg_test_sharpe"] = float(ats) if ats is not None else None
            result["avg_test_return_pct"] = float(m["avg_test_return_pct"]) if m["avg_test_return_pct"] is not None else None
            result["overfit_drop"] = float(m["overfit_drop"]) if m["overfit_drop"] is not None else None
            result["passed"] = ats is not None and float(ats) > 0
        result["note"] = "Held up out of sample." if result.get("passed") else "Did not hold up out of sample."
    else:
        result["note"] = (
            "Still running on the worker — check get_strategy_state shortly."
            if status != "failed"
            else "The out-of-sample run failed."
        )
    return result


async def _platform_or_user_credential(
    session: AsyncSession, user_id: UUID, services: list[str]
) -> Optional[tuple[UUID, str]]:
    """Find a usable trading credential (the user's or a shared platform one)
    for one of the given venue services. Returns (credential_id, service)."""
    res = await session.execute(
        text(
            "SELECT id, service FROM api_credentials "
            "WHERE service = ANY(:svcs) AND user_id IN (:uid, :platform) "
            "ORDER BY (user_id = :uid) DESC LIMIT 1"
        ),
        {"svcs": services, "uid": user_id, "platform": PLATFORM_USER_ID},
    )
    r = res.first()
    return (r[0], r[1]) if r else None


async def _start_session(
    session: AsyncSession,
    *,
    user: Any,
    strategy_row: dict[str, Any],
    credential_id: UUID,
    mode: str,
) -> UUID:
    name = strategy_row["name"]
    meta = await _latest_backtest_meta(session, user.id, name)
    symbols = list(meta["symbols"]) if meta and meta.get("symbols") else None
    if not symbols:
        raise ToolError("This strategy has no symbols to trade — backtest it first.")
    paper_asset = _ASSET_CLASS_TO_PAPER.get((strategy_row.get("asset_class") or "stocks").lower(), "equity")
    bar_resolution = (meta or {}).get("bar_resolution") or "1h"

    starting_cash = Decimal("100000")
    # Mandatory real-money guardrails for live; None for paper.
    max_order_notional: Decimal | None = None
    max_daily_loss: Decimal | None = None
    if mode == "live":
        max_daily_loss = (starting_cash * Decimal("0.02")).quantize(Decimal("1"))
        max_order_notional = (starting_cash * Decimal("0.10")).quantize(Decimal("1"))

    session_id = await P.create_paper_session(
        session,
        user_id=user.id,
        org_id=user.org_id,
        api_credential_id=credential_id,
        strategy_name=name,
        params_json={},
        symbols=symbols,
        asset_class=paper_asset,
        bar_resolution=bar_resolution,
        starting_cash=starting_cash,
        max_order_notional=max_order_notional,
        cancel_open_on_stop=True,
        mode=mode,
        max_daily_loss=max_daily_loss,
    )
    await session.commit()
    try:
        r = await _get_redis()
        import orjson

        await r.lpush(
            QUEUE_PAPER_CONTROL,
            orjson.dumps({"action": "start", "session_id": str(session_id)}).decode(),
        )
    except Exception as e:  # noqa: BLE001
        log.error("copilot.session_control_push_failed id=%s err=%s", session_id, e)
    return session_id


async def _tool_start_forward_test(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    state = await compute_strategy_state(session, user_id=user.id, strategy_row=row)
    if not state["gates_passed"]["oos_passed"]:
        raise ToolError(
            "This strategy hasn't passed the out-of-sample test yet — run that "
            "first. Forward testing comes after OOS."
        )
    cred = await _platform_or_user_credential(session, user.id, ["alpaca"])
    if cred is None:
        raise ToolError(
            "No paper-trading credential is available. Connect an Alpaca paper "
            "key (or have the platform Alpaca key configured)."
        )
    session_id = await _start_session(
        session, user=user, strategy_row=row, credential_id=cred[0], mode="paper"
    )
    return {
        "ok": True,
        "forward_session_id": str(session_id),
        "status": "starting",
        "stage": "forward",
        "note": "Forward test started on paper fills against live bars.",
    }


async def _tool_promote_strategy(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    if not inp.get("user_confirmed"):
        raise ToolError(
            "Promotion to deployable needs the user's explicit confirmation. "
            "Ask them to confirm, then call again with user_confirmed=true."
        )
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    state = await compute_strategy_state(session, user_id=user.id, strategy_row=row)
    if state["stage"] not in ("forward", "deployable", "bayn_eligible"):
        raise ToolError(
            f"This strategy is at '{state['stage']}'. It must be forward-tested "
            "before it can be promoted to deployable."
        )
    await set_strategy_lifecycle_milestone(
        session, strategy_id=row["id"], user_id=user.id, promoted=True
    )
    await session.commit()
    return {"ok": True, "strategy_id": str(row["id"]), "stage": "deployable"}


async def _tool_deploy_strategy(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    mode = inp.get("mode")
    if mode not in ("paper", "live"):
        raise ToolError("mode must be 'paper' or 'live'.")
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    state = await compute_strategy_state(session, user_id=user.id, strategy_row=row)
    if state["stage"] not in ("deployable", "bayn_eligible"):
        raise ToolError(
            f"This strategy is at '{state['stage']}'. Promote it to deployable "
            "before deploying."
        )
    if mode == "live" and not inp.get("user_confirmed"):
        raise ToolError(
            "Live deployment trades REAL money and needs explicit confirmation. "
            "Confirm with the user, then call again with user_confirmed=true."
        )

    services = ["alpaca"] if mode == "paper" else ["alpaca_live", "binanceus"]
    cred = await _platform_or_user_credential(session, user.id, services)
    if cred is None:
        raise ToolError(
            "No paper-trading credential is available." if mode == "paper"
            else "No live trading credential is available — connect an Alpaca "
            "live or Binance.US key before going live."
        )
    session_id = await _start_session(
        session, user=user, strategy_row=row, credential_id=cred[0], mode=mode
    )
    await set_strategy_lifecycle_milestone(
        session, strategy_id=row["id"], user_id=user.id, deployed_mode=mode
    )
    await session.commit()
    return {
        "ok": True,
        "strategy_id": str(row["id"]),
        "session_id": str(session_id),
        "mode": mode,
        "stage": "bayn_eligible" if mode == "live" else "deployable",
        "note": (
            "Deployed live with real-money guardrails (daily-loss halt + per-order cap)."
            if mode == "live"
            else "Deployed to a paper account."
        ),
    }


async def _tool_submit_to_bayn(
    inp: dict[str, Any], *, session: AsyncSession, user: Any, **_: Any
) -> dict[str, Any]:
    if not inp.get("user_confirmed"):
        raise ToolError(
            "Submitting to the desk needs the user's confirmation. Ask, then "
            "call again with user_confirmed=true."
        )
    row = await _load_strategy_or_raise(session, user.id, inp["strategy_id"])
    state = await compute_strategy_state(session, user_id=user.id, strategy_row=row)
    if state["stage"] != "bayn_eligible":
        raise ToolError(
            f"This strategy is at '{state['stage']}'. Only a live-deployed "
            "(Bayn-eligible) strategy can be submitted to the desk."
        )
    res = await session.execute(
        text(
            """
            INSERT INTO bayn_submissions (user_id, org_id, strategy_id, strategy_name)
            VALUES (:uid, :org, :sid, :name)
            RETURNING id
            """
        ),
        {"uid": user.id, "org": user.org_id, "sid": row["id"], "name": row["name"]},
    )
    submission_id = res.scalar_one()
    await set_strategy_lifecycle_milestone(
        session, strategy_id=row["id"], user_id=user.id, submitted=True
    )
    await session.commit()
    return {
        "ok": True,
        "submission_id": str(submission_id),
        "status": "pending_review",
        "note": "Submitted to the Bayn desk for review.",
    }


_DISPATCH = {
    "get_strategy_state": _tool_get_strategy_state,
    "build_strategy": _tool_build_strategy,
    "edit_strategy_node": _tool_edit_strategy_node,
    "run_backtest": _tool_run_backtest,
    "get_backtest_analysis": _tool_get_backtest_analysis,
    "run_oos_test": _tool_run_oos_test,
    "start_forward_test": _tool_start_forward_test,
    "promote_strategy": _tool_promote_strategy,
    "deploy_strategy": _tool_deploy_strategy,
    "submit_to_bayn": _tool_submit_to_bayn,
}


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ToolError(f"'{s}' isn't a valid ISO date.")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def dispatch_tool(
    name: str,
    tool_input: dict[str, Any],
    *,
    session: AsyncSession,
    user: Any,
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Execute one tool call. Always returns a JSON-serialisable dict; failures
    come back as {ok: false, error} rather than raising, so the agent can react."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    try:
        return await fn(tool_input, session=session, user=user, registry=registry)
    except ToolError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        log.exception("copilot.tool_failed name=%s", name)
        # Roll back any partial write so the request session stays usable.
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
