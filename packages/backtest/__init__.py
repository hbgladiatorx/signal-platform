"""Backtest engine.

Public API:

    from packages.backtest import (
        run_backtest,
        BacktestConfig,
        BacktestResult,
        Fill,
        Position,
        EquityPoint,
    )

See packages/backtest/engine.py for `run_backtest()` semantics.
See packages/backtest/types.py for the data structures.
"""
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
    "BacktestConfig",
    "BacktestResult",
    "EquityPoint",
    "Fill",
    "Portfolio",
    "Position",
    "run_backtest",
]
