"""Backtest engine.

Public API:

    from packages.backtest import (
        run_backtest,
        BacktestConfig,
        BacktestResult,
        Fill,
        Position,
        EquityPoint,
        compute_analytics,
        BacktestAnalytics,
        RoundTrip,
    )

See packages/backtest/engine.py for `run_backtest()` semantics.
See packages/backtest/types.py for the data structures.
See packages/backtest/analytics.py for `compute_analytics()`.
"""
from packages.backtest.analytics import (
    BacktestAnalytics,
    RoundTrip,
    compute_analytics,
)
from packages.backtest.engine import run_backtest
from packages.backtest.portfolio import Portfolio
from packages.backtest.types import (
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    Fill,
    Position,
)

__all__ = [
    "BacktestAnalytics",
    "BacktestConfig",
    "BacktestResult",
    "EquityPoint",
    "Fill",
    "Portfolio",
    "Position",
    "RoundTrip",
    "compute_analytics",
    "run_backtest",
]
