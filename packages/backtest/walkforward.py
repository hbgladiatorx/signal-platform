"""Walk-forward analysis orchestration.

Given a strategy, symbol(s), parameter grid, and window config, run a
rolling train/test sequence:

For each of N windows:
  1. Train segment: run all param combos on this segment, pick the
     best by `selection_metric`.
  2. Test segment (immediately following train): run a single backtest
     with the best params; record its metrics.

The aggregate of test-segment performance is the walk-forward "honest"
estimate of how the strategy would have performed in live trading —
because the test segment was never seen during parameter selection.

This module exposes `run_walkforward()` which the backtest_worker calls
when a job is popped from QUEUE_WALKFORWARD_JOBS.
"""
from __future__ import annotations

import itertools
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from packages.backtest import BacktestConfig, compute_analytics, run_backtest


log = logging.getLogger(__name__)


# ============================================================
# Selection metrics: how to pick the best combo from a train sweep
# ============================================================
def _safe_metric(value: Any) -> float:
    """Treat None/NaN as -inf so it never wins."""
    if value is None:
        return float("-inf")
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    if f != f:  # NaN check
        return float("-inf")
    return f


SELECTION_METRICS: dict[str, Any] = {
    "sharpe":       lambda a: _safe_metric(getattr(a, "sharpe_ratio", None)),
    "sortino":      lambda a: _safe_metric(getattr(a, "sortino_ratio", None)),
    "total_return": lambda a: _safe_metric(getattr(a, "total_return_pct", None)),
    "calmar":       lambda a: _safe_metric(getattr(a, "calmar_ratio", None)),
}


# ============================================================
# Result dataclasses (JSON-serialized into walkforwards.windows_result)
# ============================================================
@dataclass
class WindowResult:
    window_index: int
    train_start_ts: str    # ISO timestamp
    train_end_ts: str
    test_start_ts: str
    test_end_ts: str
    best_params: dict[str, Any]
    # Best-combo train metrics
    train_sharpe: float | None
    train_total_return_pct: float | None
    train_max_drawdown_pct: float | None
    train_num_closed_trades: int
    # Test metrics (using best params on held-out segment)
    test_sharpe: float | None
    test_total_return_pct: float | None
    test_max_drawdown_pct: float | None
    test_num_closed_trades: int


@dataclass
class WalkforwardResult:
    total_combos: int
    total_backtests_run: int
    duration_seconds: float
    windows: list[WindowResult]
    avg_train_sharpe: float | None
    avg_test_sharpe: float | None
    avg_test_return_pct: float | None
    overfit_drop: float | None         # avg_train_sharpe - avg_test_sharpe
    win_rate_windows_pct: float | None # % of windows where test return > 0


# ============================================================
# Cartesian product over param grid
# ============================================================
def expand_grid(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of param values. Returns [{}] for empty grid."""
    if not param_grid:
        return [{}]
    keys = sorted(param_grid.keys())
    value_lists = [list(param_grid[k]) for k in keys]
    return [dict(zip(keys, vals)) for vals in itertools.product(*value_lists)]


# ============================================================
# Window slicing
# ============================================================
def compute_windows(
    bars: dict[str, pd.DataFrame],
    train_bars: int,
    test_bars: int,
    num_windows: int,
) -> list[tuple[int, int, int, int]]:
    """Compute (train_start, train_end, test_start, test_end) bar indices
    for each window. Windows roll forward by test_bars (test segments do
    not overlap). The most recent window's test segment ends at the last
    available bar.

    If there isn't enough data for all requested windows, returns as many
    as fit (anchored to the end of the data).
    """
    if train_bars <= 0 or test_bars <= 0 or num_windows <= 0:
        return []

    # Limit by the shortest symbol's history
    min_bars = min(len(df) for df in bars.values())

    # How many windows can we actually fit?
    # First window needs train_bars + test_bars; each subsequent shifts by test_bars.
    # min_bars >= train_bars + num_windows * test_bars  →  num_windows <= (min_bars - train_bars) / test_bars
    max_fittable = (min_bars - train_bars) // test_bars
    if max_fittable < 1:
        return []
    effective_n = min(num_windows, max_fittable)

    # Anchor to end of data: last window's test segment ends at min_bars
    windows: list[tuple[int, int, int, int]] = []
    for i in range(effective_n):
        # i=0 → oldest window, i=effective_n-1 → most recent
        test_end = min_bars - (effective_n - 1 - i) * test_bars
        test_start = test_end - test_bars
        train_end = test_start
        train_start = train_end - train_bars
        if train_start < 0:
            continue
        windows.append((train_start, train_end, test_start, test_end))
    return windows


def slice_bars(
    bars: dict[str, pd.DataFrame],
    start_idx: int,
    end_idx: int,
) -> dict[str, pd.DataFrame]:
    """Return a new bars dict where each DataFrame is sliced [start_idx:end_idx)."""
    return {sym: df.iloc[start_idx:end_idx].copy() for sym, df in bars.items()}


# ============================================================
# Single window
# ============================================================
def _run_window(
    strategy_cls,
    symbols: list[str],
    all_bars: dict[str, pd.DataFrame],
    train_slice: tuple[int, int],
    test_slice: tuple[int, int],
    param_combos: list[dict[str, Any]],
    config: BacktestConfig,
    selection_metric: str,
    window_index: int,
) -> WindowResult:
    """Run one window: sweep on train segment, pick best, evaluate on test."""
    tr_start, tr_end = train_slice
    te_start, te_end = test_slice

    train_bars = slice_bars(all_bars, tr_start, tr_end)
    test_bars = slice_bars(all_bars, te_start, te_end)

    metric_fn = SELECTION_METRICS.get(selection_metric, SELECTION_METRICS["sharpe"])

    best_combo: dict[str, Any] | None = None
    best_metric_value = float("-inf")
    best_train_analytics = None

    combos_succeeded = 0
    for combo in param_combos:
        try:
            params = strategy_cls.PARAMS_MODEL(**combo)
            strategy = strategy_cls(symbols=symbols, params=params)
            result = run_backtest(strategy, train_bars, config)
            analytics = compute_analytics(result)
        except Exception as e:
            log.warning(
                "walkforward.combo_failed",
                extra={"window_index": window_index, "combo": combo, "err": str(e)},
            )
            continue

        combos_succeeded += 1
        metric_value = metric_fn(analytics)
        if metric_value > best_metric_value:
            best_metric_value = metric_value
            best_combo = combo
            best_train_analytics = analytics

    if best_combo is None or best_train_analytics is None:
        raise RuntimeError(
            f"Window {window_index}: no param combo produced a valid result "
            f"on the training segment "
            f"(tried {len(param_combos)} combos, {combos_succeeded} succeeded)"
        )

    # Run test segment with the best params
    test_params = strategy_cls.PARAMS_MODEL(**best_combo)
    test_strategy = strategy_cls(symbols=symbols, params=test_params)
    test_result = run_backtest(test_strategy, test_bars, config)
    test_analytics = compute_analytics(test_result)

    # Pull window timestamps from the first symbol's index
    first_sym = symbols[0]
    tr_df = all_bars[first_sym].iloc[tr_start:tr_end]
    te_df = all_bars[first_sym].iloc[te_start:te_end]

    def _f(v: Any) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f:
            return None
        return f

    return WindowResult(
        window_index=window_index,
        train_start_ts=tr_df.index[0].isoformat(),
        train_end_ts=tr_df.index[-1].isoformat(),
        test_start_ts=te_df.index[0].isoformat(),
        test_end_ts=te_df.index[-1].isoformat(),
        best_params=best_combo,
        train_sharpe=_f(getattr(best_train_analytics, "sharpe_ratio", None)),
        train_total_return_pct=_f(getattr(best_train_analytics, "total_return_pct", None)),
        train_max_drawdown_pct=_f(getattr(best_train_analytics, "max_drawdown_pct", None)),
        train_num_closed_trades=int(getattr(best_train_analytics, "num_closed_trades", 0) or 0),
        test_sharpe=_f(getattr(test_analytics, "sharpe_ratio", None)),
        test_total_return_pct=_f(getattr(test_analytics, "total_return_pct", None)),
        test_max_drawdown_pct=_f(getattr(test_analytics, "max_drawdown_pct", None)),
        test_num_closed_trades=int(getattr(test_analytics, "num_closed_trades", 0) or 0),
    )


# ============================================================
# Top-level orchestration
# ============================================================
def run_walkforward(
    *,
    strategy_cls,
    symbols: list[str],
    all_bars: dict[str, pd.DataFrame],
    param_grid: dict[str, list[Any]],
    train_bars: int,
    test_bars: int,
    num_windows: int,
    config: BacktestConfig,
    selection_metric: str = "sharpe",
) -> WalkforwardResult:
    """Run walk-forward analysis. See module docstring."""
    start_time = time.time()

    if selection_metric not in SELECTION_METRICS:
        raise ValueError(
            f"Unknown selection_metric={selection_metric!r}. "
            f"Allowed: {list(SELECTION_METRICS.keys())}"
        )

    param_combos = expand_grid(param_grid)
    windows = compute_windows(all_bars, train_bars, test_bars, num_windows)

    if not windows:
        min_bars = min(len(df) for df in all_bars.values()) if all_bars else 0
        raise RuntimeError(
            f"Insufficient data for walk-forward: need at least "
            f"{train_bars + test_bars} bars, have {min_bars}."
        )

    log.info(
        "walkforward.start",
        extra={
            "combos": len(param_combos),
            "windows": len(windows),
            "requested_windows": num_windows,
            "train_bars": train_bars,
            "test_bars": test_bars,
        },
    )

    results: list[WindowResult] = []
    for i, (tr_start, tr_end, te_start, te_end) in enumerate(windows):
        win = _run_window(
            strategy_cls=strategy_cls,
            symbols=symbols,
            all_bars=all_bars,
            train_slice=(tr_start, tr_end),
            test_slice=(te_start, te_end),
            param_combos=param_combos,
            config=config,
            selection_metric=selection_metric,
            window_index=i,
        )
        results.append(win)
        log.info(
            "walkforward.window_done",
            extra={
                "window_index": i,
                "best_params": win.best_params,
                "train_sharpe": win.train_sharpe,
                "test_sharpe": win.test_sharpe,
                "test_return_pct": win.test_total_return_pct,
            },
        )

    # Aggregates
    train_sharpes = [w.train_sharpe for w in results if w.train_sharpe is not None]
    test_sharpes = [w.test_sharpe for w in results if w.test_sharpe is not None]
    test_returns = [w.test_total_return_pct for w in results if w.test_total_return_pct is not None]

    avg_train_sharpe = sum(train_sharpes) / len(train_sharpes) if train_sharpes else None
    avg_test_sharpe = sum(test_sharpes) / len(test_sharpes) if test_sharpes else None
    avg_test_return = sum(test_returns) / len(test_returns) if test_returns else None
    overfit_drop = (
        avg_train_sharpe - avg_test_sharpe
        if avg_train_sharpe is not None and avg_test_sharpe is not None
        else None
    )
    win_rate = (
        sum(1 for r in test_returns if r > 0) / len(test_returns) * 100
        if test_returns
        else None
    )

    duration = time.time() - start_time
    total_backtests = len(param_combos) * len(results) + len(results)  # train sweeps + test runs

    return WalkforwardResult(
        total_combos=len(param_combos),
        total_backtests_run=total_backtests,
        duration_seconds=duration,
        windows=results,
        avg_train_sharpe=avg_train_sharpe,
        avg_test_sharpe=avg_test_sharpe,
        avg_test_return_pct=avg_test_return,
        overfit_drop=overfit_drop,
        win_rate_windows_pct=win_rate,
    )


# ============================================================
# Helpers exported for the persistence layer
# ============================================================
def windows_to_json(windows: list[WindowResult]) -> list[dict[str, Any]]:
    """Serialize WindowResult list to JSON-compatible dicts."""
    return [asdict(w) for w in windows]
