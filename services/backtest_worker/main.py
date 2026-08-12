"""Backtest worker service.

Pops backtest job UUIDs from the Redis LIST `backtest:jobs` (BRPOP) and
executes each backtest end-to-end.

Job lifecycle (per backtest):
  1. Load header from DB. If status != 'pending', skip (already processed).
  2. mark_backtest_running()  → status='running', stamps started_at.
  3. Load bars from the cagg table matching bar_resolution.
  4. Discover and instantiate the strategy via packages.strategy.registry.
  5. run_backtest(strategy, bars, BacktestConfig(...))
  6. compute_analytics(result)
  7. save_backtest_results()  → status='completed', stamps completed_at,
     writes trades and equity points.

On any exception during steps 3-7: mark_backtest_failed() with the
traceback as the error message. The job is then considered done (no
retry in Phase 2).

Design notes:
  - BRPOP with a 5-second timeout — lets us check shutdown_event between
    blocking reads so SIGTERM works promptly.
  - Single-threaded by design. Scale-out is achieved by running multiple
    backtest_worker containers (Redis BRPOP is atomic; each job goes to
    exactly one worker).
  - Strategies are discovered once at startup. To pick up new strategies
    a worker must be restarted.
  - This service does NOT enqueue jobs. Job creation is the API's job
    (Step 23) or a manual LPUSH (used in verification).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal as signal_module
import sys
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Type
from uuid import UUID

import pandas as pd
import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.backtest import (
    BacktestConfig,
    attribution_to_dict,
    compute_analytics,
    compute_attribution,
    run_backtest,
)
from packages.analysis import analyze_backtest, generate_narrative
from packages.ml import (
    build_dataset,
    extract_samples,
    model_to_dict,
    train_signal_edge_model,
)
from packages.ml.persistence import save_training_samples
from packages.backtest.instruments import load_instrument_meta
from packages.backtest.walkforward import run_walkforward
from packages.backtest.walkforward_persistence import (
    load_walkforward,
    mark_walkforward_failed,
    mark_walkforward_running,
    reclaim_stale_walkforwards,
    save_walkforward_results,
)
from packages.backtest.persistence import (
    load_backtest,
    mark_backtest_failed,
    mark_backtest_running,
    reclaim_stale_backtests,
    save_backtest_results,
)
from packages.core.ai_provider import (
    resolve_ai_provider,
    set_request_ai_config,
)
from packages.data.db import get_engine
from packages.data.messagebus import QUEUE_BACKTEST_JOBS, QUEUE_WALKFORWARD_JOBS
from packages.livetrade.bars import load_bars
from packages.strategy.base import Strategy
from packages.strategy.registry import discover_strategies
from packages.data.db import session_scope
from packages.strategy.loader import StrategyLoadError
from packages.strategy.resolver import StrategyNotFoundError, resolve_strategy


# ============================================================
# Logging
# ============================================================
def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


_configure_logging()
log = structlog.get_logger(__name__)


# ============================================================
# Constants
# ============================================================
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
WORKER_NAME = os.environ.get("HOSTNAME", "backtest-worker-1")
POP_TIMEOUT_S = 5  # BRPOP blocking time

# A job killed mid-run (OOM, restart, SIGKILL) never reaches its failure
# handler, so it stays 'running' forever and the UI renders an all-zero result.
# On startup we fail any 'running' row older than this, leaving a sibling
# worker's genuinely in-flight job alone (real runs finish in seconds-minutes).
STALE_RUNNING_SECONDS = int(os.environ.get("BACKTEST_STALE_RUNNING_SECONDS", "1800"))

# Upper bound on bars a single backtest may span. Two reasons to cap it:
#   1. Memory — the engine builds a per-bar equity curve and materializes bars as
#      pandas Series, so RAM scales with bar count (OOM risk at the high end).
#   2. Throughput — the engine runs ~200-250 bars/sec and the worker processes
#      ONE job at a time, so a huge run (e.g. crypto 1m over years ≈ 700k bars ≈
#      ~50 min) blocks the queue and every other backtest sits 'pending'.
# 250k ≈ a few minutes worst-case and still covers ~1y of 1-minute stock data;
# multi-year 1-minute runs are rejected with an actionable "use a coarser
# resolution" message rather than jamming the worker. Env-tunable.
MAX_BACKTEST_BARS = int(os.environ.get("BACKTEST_MAX_BARS", "250000"))

STRATEGIES_DIR = Path("/app/strategies")


# Bar loading is shared with the live paper-trading runner; see
# packages/livetrade/bars.py. `_load_bars` remains as a thin alias so the
# existing call sites and any external imports keep working.
_load_bars = load_bars


# ============================================================
# Job processing
# ============================================================
async def _process_job(
    backtest_id: UUID,
    engine: AsyncEngine,
    strategies_cache: dict[str, Type[Strategy]],
) -> None:
    """Process one backtest job end-to-end."""
    log.info("backtest_worker.job.start", backtest_id=str(backtest_id))

    # ----- 1) Load header -----
    async with engine.connect() as conn:
        header = await load_backtest(conn, backtest_id)

    if header is None:
        log.error(
            "backtest_worker.job.not_found",
            backtest_id=str(backtest_id),
        )
        return

    if header["status"] != "pending":
        log.warning(
            "backtest_worker.job.not_pending",
            backtest_id=str(backtest_id),
            status=header["status"],
        )
        return

    # ----- 2) Mark running -----
    async with engine.begin() as conn:
        await mark_backtest_running(conn, backtest_id)

    # ----- 3-7) Execute with failure capture -----
    try:
        strategy_name = header["strategy_name"]
        symbols = list(header["symbols"])
        resolution = header["bar_resolution"]
        params_dict = header["params_json"] or {}

        # 3a) Resolve strategy (built-in or user-authored)
        async with session_scope() as session:
            try:
                resolved = await resolve_strategy(
                    session,
                    user_id=header["user_id"],
                    strategy_name=strategy_name,
                    builtin_registry=strategies_cache,
                )
            except StrategyNotFoundError:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} not found in built-ins or "
                    f"the owner's user_strategies."
                )
            except StrategyLoadError as e:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} failed to compile: {e}"
                )
        strategy_cls = resolved.cls

        # 3b) Validate params
        params = strategy_cls.PARAMS_MODEL(**params_dict)

        # 3c) Instantiate strategy
        strategy = strategy_cls(symbols=symbols, params=params)

        # 4) Load bars. A requested window (window_start/window_end) bounds the
        # run to a date range — e.g. a held-out out-of-sample segment. NULL on
        # both means full history. The window is pushed into the SQL query so we
        # only materialize bars inside the range, never the symbol's full
        # history (loading 5 years to test 1 month was the memory amplifier
        # behind the OOM). Bars come back tz-aware UTC, indexed by bucket.
        window_start = header.get("window_start")
        window_end = header.get("window_end")
        bars: dict[str, pd.DataFrame] = {}
        bars_start = None
        bars_end = None
        max_bar_count = 0
        for symbol in symbols:
            df = await _load_bars(
                engine, symbol, resolution,
                start=window_start, end=window_end,
            )
            if df.empty:
                if window_start is not None or window_end is not None:
                    raise RuntimeError(
                        f"No bars for {symbol!r} at resolution {resolution!r} "
                        f"within the requested window "
                        f"[{window_start}, {window_end}]"
                    )
                raise RuntimeError(
                    f"No bars available for {symbol!r} at resolution {resolution!r}"
                )
            bars[symbol] = df
            if bars_start is None or df.index[0] < bars_start:
                bars_start = df.index[0]
            if bars_end is None or df.index[-1] > bars_end:
                bars_end = df.index[-1]
            max_bar_count = max(max_bar_count, len(df))

        # Pre-flight memory guard: engine memory scales with total bars across
        # all symbols (per-bar equity curve + bars materialized as Series), so
        # reject oversized runs with an actionable error rather than letting the
        # worker OOM and strand the job in 'running'.
        total_bar_count = sum(len(df) for df in bars.values())
        if total_bar_count > MAX_BACKTEST_BARS:
            raise RuntimeError(
                f"Backtest spans {total_bar_count:,} bars across {len(symbols)} "
                f"symbol(s) at {resolution!r} (limit {MAX_BACKTEST_BARS:,}). "
                f"Narrow the date range or use a coarser bar resolution."
            )

        log.info(
            "backtest_worker.job.bars_loaded",
            backtest_id=str(backtest_id),
            symbols=symbols,
            bars=max_bar_count,
            total_bars=total_bar_count,
            bars_start=str(bars_start),
            bars_end=str(bars_end),
        )

        # 5) Run backtest. Load instrument metadata so options get their
        # contract multiplier + expiry settlement; for crypto/equity this is a
        # no-op (multiplier 1, no expiry).
        instrument_meta = await load_instrument_meta(engine, symbols)
        config = BacktestConfig(
            starting_cash=Decimal(str(header["starting_cash"])),
            fee_rate_bps=int(header["fee_rate_bps"]),
            slippage_bps=int(header["slippage_bps"]),
            instrument_meta=instrument_meta,
        )
        result = run_backtest(strategy, bars, config)

        # 6) Compute analytics (the "how well"), attribution (the "why"), and
        #    the signal-edge model (which signals predict profitable trades).
        analytics = compute_analytics(result)
        attribution = compute_attribution(result, analytics)
        dataset = build_dataset(result, analytics)
        model = train_signal_edge_model(dataset)
        ml_model_json = model_to_dict(model) if dataset.n_samples > 0 else None
        # Deterministic analysis (the "what worked / why / what to fix"): derived
        # from the metrics + attribution + ml model. The optional LLM narrative
        # is generated on-demand by the API, not here (keeps the worker fast).
        analysis_json = analyze_backtest(
            {
                "total_return_pct": analytics.total_return_pct,
                "annualized_return_pct": analytics.annualized_return_pct,
                "sharpe_ratio": analytics.sharpe_ratio,
                "sortino_ratio": analytics.sortino_ratio,
                "max_drawdown_pct": analytics.max_drawdown_pct,
                "calmar_ratio": analytics.calmar_ratio,
                "num_closed_trades": analytics.num_closed_trades,
                "win_rate_pct": analytics.win_rate_pct,
                "avg_winner_pct": analytics.avg_winner_pct,
                "avg_loser_pct": analytics.avg_loser_pct,
                "profit_factor": analytics.profit_factor,
                "orders_submitted": result.orders_submitted,
            },
            attribution_to_dict(attribution) if attribution is not None else None,
            ml_model_json,
        )
        # AI narrative: now that a funded Anthropic key is configured, generate the
        # plain-English "what worked / why / what to fix" prose inline so the detail
        # page shows the full AI analysis automatically — no "Explain with AI" click.
        # Best-effort: degrades to the deterministic findings if the LLM is down or
        # out of credit, and only runs when there's a substantive analysis to narrate.
        if analysis_json and analytics.num_closed_trades > 0:
            try:
                # Auto-narration runs on the backtest OWNER's own AI provider.
                # If they haven't connected one, narration is simply skipped.
                async with engine.connect() as key_conn:
                    owner_cfg = await resolve_ai_provider(key_conn, header["user_id"])
                set_request_ai_config(owner_cfg)
                narration = generate_narrative(analysis_json, strategy_name=strategy_name)
                if narration.ok and narration.narrative:
                    analysis_json["narrative"] = narration.narrative
                else:
                    log.info("backtest_worker.narrative.skipped", reason=narration.error)
            except Exception:  # noqa: BLE001 — never fail a backtest over narration
                log.warning("backtest_worker.narrative.error", exc_info=True)
        # Portable per-trip samples for the cross-backtest store (Phase 4).
        training_samples = extract_samples(result, analytics)

        log.info(
            "backtest_worker.job.computed",
            backtest_id=str(backtest_id),
            fills=result.num_trades,
            closed_trips=analytics.num_closed_trades,
            total_return_pct=analytics.total_return_pct,
            best_symbol=attribution.best_symbol,
            best_signal=attribution.best_signal,
            model_fitted=model.fitted,
            model_samples=model.n_samples,
        )

        # 7) Persist
        async with engine.begin() as conn:
            await save_backtest_results(
                conn,
                backtest_id,
                result,
                analytics,
                attribution=attribution,
                ml_model_json=ml_model_json,
                analysis_json=analysis_json,
                bars_start=bars_start.to_pydatetime() if bars_start else None,
                bars_end=bars_end.to_pydatetime() if bars_end else None,
                num_bars=max_bar_count,
            )
            # Accumulate this run's trips into the cross-backtest store, in the
            # same transaction so samples and the saved backtest stay in sync.
            await save_training_samples(
                conn,
                backtest_id,
                header["user_id"],
                strategy_name,
                training_samples,
            )

        log.info(
            "backtest_worker.job.completed",
            backtest_id=str(backtest_id),
        )

    except Exception as e:
        # Capture the traceback for debugging; truncate by the persistence
        # layer if too long.
        error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        log.error(
            "backtest_worker.job.failed",
            backtest_id=str(backtest_id),
            err=str(e),
        )
        try:
            async with engine.begin() as conn:
                await mark_backtest_failed(conn, backtest_id, error_msg)
        except Exception as inner_e:
            log.error(
                "backtest_worker.job.cannot_mark_failed",
                backtest_id=str(backtest_id),
                err=str(inner_e),
            )


# ============================================================
# Main loop



# ============================================================
# Walkforward job processing
# ============================================================
async def _process_walkforward_job(
    walkforward_id: UUID,
    engine: AsyncEngine,
    strategies_cache: dict[str, Type[Strategy]],
) -> None:
    """Process one walk-forward job end-to-end."""
    log.info("backtest_worker.walkforward.start", walkforward_id=str(walkforward_id))

    async with engine.connect() as conn:
        header = await load_walkforward(conn, walkforward_id)
    if header is None:
        log.error("backtest_worker.walkforward.not_found", walkforward_id=str(walkforward_id))
        return
    if header["status"] != "pending":
        log.warning("backtest_worker.walkforward.not_pending",
                    walkforward_id=str(walkforward_id), status=header["status"])
        return

    async with engine.begin() as conn:
        await mark_walkforward_running(conn, walkforward_id)

    try:
        strategy_name = header["strategy_name"]
        symbols = list(header["symbols"])
        resolution = header["bar_resolution"]
        param_grid = header["param_grid"] or {}

        async with session_scope() as session:
            try:
                resolved = await resolve_strategy(
                    session,
                    user_id=header["user_id"],
                    strategy_name=strategy_name,
                    builtin_registry=strategies_cache,
                )
            except StrategyNotFoundError:
                raise RuntimeError(f"Strategy {strategy_name!r} not found")
            except StrategyLoadError as e:
                raise RuntimeError(f"Strategy {strategy_name!r} failed to compile: {e}")
        strategy_cls = resolved.cls

        bars: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = await _load_bars(engine, symbol, resolution)
            if df.empty:
                raise RuntimeError(f"No bars available for {symbol!r} at resolution {resolution!r}")
            bars[symbol] = df

        instrument_meta = await load_instrument_meta(engine, symbols)
        config = BacktestConfig(
            starting_cash=Decimal(str(header["starting_cash"])),
            fee_rate_bps=int(header["fee_rate_bps"]),
            slippage_bps=int(header["slippage_bps"]),
            instrument_meta=instrument_meta,
        )
        result = run_walkforward(
            strategy_cls=strategy_cls,
            symbols=symbols,
            all_bars=bars,
            param_grid=param_grid,
            train_bars=int(header["train_bars"]),
            test_bars=int(header["test_bars"]),
            num_windows=int(header["num_windows"]),
            config=config,
            selection_metric=header["selection_metric"],
        )

        async with engine.begin() as conn:
            await save_walkforward_results(conn, walkforward_id, result)

        log.info("backtest_worker.walkforward.completed",
                 walkforward_id=str(walkforward_id),
                 windows=len(result.windows),
                 duration_s=result.duration_seconds)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        log.error("backtest_worker.walkforward.failed",
                  walkforward_id=str(walkforward_id), err=str(e))
        try:
            async with engine.begin() as conn:
                await mark_walkforward_failed(conn, walkforward_id, error_msg)
        except Exception as inner_e:
            log.error("backtest_worker.walkforward.cannot_mark_failed",
                      walkforward_id=str(walkforward_id), err=str(inner_e))


# ============================================================
async def main_loop() -> None:
    # socket_timeout comfortably exceeds the BRPOP block so an idle (empty-queue)
    # poll returns cleanly instead of racing the socket read into a timeout — the
    # source of the noisy "brpop_error" spam. Keepalive + health checks keep the
    # blocking connection fresh.
    redis_client: redis.Redis = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=POP_TIMEOUT_S + 15,
        socket_keepalive=True,
        health_check_interval=30,
    )
    engine: AsyncEngine = get_engine()

    strategies_cache: dict[str, Type[Strategy]] = discover_strategies(STRATEGIES_DIR)

    log.info(
        "backtest_worker.starting",
        worker=WORKER_NAME,
        queue=QUEUE_BACKTEST_JOBS,
        pop_timeout_s=POP_TIMEOUT_S,
        strategies=list(strategies_cache.keys()),
    )

    # Recover orphans: jobs a previous worker left stranded in 'running' when it
    # was killed mid-run. Without this they stay 'running' forever and surface
    # as fake all-zero results. Best-effort — never block startup on it.
    try:
        async with engine.begin() as conn:
            stale_bt = await reclaim_stale_backtests(conn, STALE_RUNNING_SECONDS)
            stale_wf = await reclaim_stale_walkforwards(conn, STALE_RUNNING_SECONDS)
        if stale_bt or stale_wf:
            log.warning(
                "backtest_worker.reclaimed_orphans",
                backtests=[str(i) for i in stale_bt],
                walkforwards=[str(i) for i in stale_wf],
                stale_after_s=STALE_RUNNING_SECONDS,
            )
    except Exception as e:  # noqa: BLE001 — recovery must not crash the worker
        log.error("backtest_worker.reclaim_failed", err=str(e))

    shutdown_event = asyncio.Event()

    def _on_signal(sig: int) -> None:
        log.info("backtest_worker.signal", sig=sig)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal_module.SIGINT, signal_module.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            pass

    while not shutdown_event.is_set():
        try:
            # BRPOP returns (key, value) tuple or None on timeout
            popped = await redis_client.brpop(
                [QUEUE_WALKFORWARD_JOBS, QUEUE_BACKTEST_JOBS],
                timeout=POP_TIMEOUT_S,
            )
        except redis.TimeoutError:
            # Idle empty-queue poll racing the socket read — expected, not an
            # error. Loop and check shutdown_event again (no backoff needed).
            continue
        except Exception as e:
            log.error("backtest_worker.brpop_error", err=str(e))
            await asyncio.sleep(1.0)
            continue

        if popped is None:
            # Timeout; loop and check shutdown_event again
            continue

        _queue_name, value = popped
        try:
            backtest_id = UUID(value)
        except (ValueError, TypeError):
            log.error(
                "backtest_worker.invalid_uuid_in_queue",
                value=value,
            )
            continue

        try:
            if _queue_name == QUEUE_WALKFORWARD_JOBS:
                await _process_walkforward_job(backtest_id, engine, strategies_cache)
            else:
                await _process_job(backtest_id, engine, strategies_cache)
        except Exception as e:
            # Defensive: _process_job already handles its own exceptions,
            # but catch anything that leaks to keep the loop alive.
            log.error(
                "backtest_worker.unhandled_job_error",
                backtest_id=str(backtest_id),
                err=str(e),
            )

    log.info("backtest_worker.stopping")
    await redis_client.aclose()
    await engine.dispose()
    log.info("backtest_worker.stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        sys.exit(0)
