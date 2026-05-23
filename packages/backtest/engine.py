"""Backtest engine — the main entry point.

`run_backtest(strategy, bars, config) -> BacktestResult`

Loop structure per bar in the unified timeline:

  1. UPDATE MARKS — record the latest closing price for any symbol that
     traded in this bar. We carry forward the last-known mark for symbols
     that didn't trade; that's needed because Binance.US sparseness means
     not every bar has every symbol.

  2. FILL PENDING ORDERS — orders queued at PRIOR bars try to fill against
     THIS bar's OHLC. Market orders fill at open + slippage. Limit orders
     fill if the bar's range crossed the limit price.

  3. CALL STRATEGY — build a BarContext with history up to and including
     this bar's close, current positions, current cash. Call strategy.on_bar().
     Any orders the strategy submits are queued for the NEXT bar.

  4. MARK TO MARKET — record an EquityPoint with cash + position MTM at
     this bar's close. Equity curve has one point per timeline bar.

This ordering is the key to look-ahead-bias prevention:
  - The strategy sees the bar as already closed (close price known)
  - Orders the strategy submits cannot fill in this same bar
  - The earliest they can fill is the NEXT bar's open

Inputs:
  strategy  — an already-instantiated Strategy (caller controls construction)
  bars      — dict canonical_symbol -> pd.DataFrame with columns
              [open, high, low, close, volume] and a DatetimeIndex
  config    — BacktestConfig (starting cash, fees, slippage)

Returns:
  BacktestResult with fills, equity_curve, final positions, etc.

Limitations (Phase 2):
  - Long-only
  - No margin
  - No order cancellation (limit orders persist until filled)
  - No partial fills
  - Sequential / single-threaded
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from packages.backtest.fills import simulate_market_fill, try_fill_limit_order
from packages.backtest.portfolio import Portfolio
from packages.backtest.types import (
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    Fill,
)
from packages.strategy.base import Order, OrderSide, OrderType, Strategy
from packages.strategy.context import BarContext

log = logging.getLogger(__name__)


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _validate_inputs(
    strategy: Strategy,
    bars: dict[str, pd.DataFrame],
) -> None:
    if not strategy.symbols:
        raise ValueError("Strategy has no symbols configured")
    for sym in strategy.symbols:
        if sym not in bars:
            raise ValueError(f"No bars provided for symbol {sym!r}")
        df = bars[sym]
        if df.empty:
            raise ValueError(f"Bars for {sym!r} are empty")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                f"Bars for {sym!r} missing required columns: {missing}"
            )
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(
                f"Bars for {sym!r} must be indexed by DatetimeIndex; "
                f"got {type(df.index).__name__}"
            )


def run_backtest(
    strategy: Strategy,
    bars: dict[str, pd.DataFrame],
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Execute a backtest. See module docstring for semantics."""
    if config is None:
        config = BacktestConfig()
    _validate_inputs(strategy, bars)

    # ----- Build unified timeline -----
    all_ts: set[pd.Timestamp] = set()
    for sym in strategy.symbols:
        all_ts.update(bars[sym].index)
    timeline = sorted(all_ts)
    if not timeline:
        raise ValueError("Empty timeline: no bars across all symbols")

    # Fast lookup: symbol -> {ts -> bar row}
    bar_by_ts: dict[str, dict[pd.Timestamp, pd.Series]] = {
        sym: {idx: row for idx, row in bars[sym].iterrows()}
        for sym in strategy.symbols
    }

    # ----- Initialize state -----
    portfolio = Portfolio(config.starting_cash)
    strategy.on_init()

    fills: list[Fill] = []
    equity_curve: list[EquityPoint] = []
    rejected_orders: list[tuple[Order, str]] = []
    pending_orders: list[Order] = []
    last_marks: dict[str, Decimal] = {}

    # ----- Walk timeline -----
    for ts in timeline:
        # --- (1) UPDATE MARKS ---
        for sym in strategy.symbols:
            this_bar = bar_by_ts.get(sym, {}).get(ts)
            if this_bar is not None:
                last_marks[sym] = Decimal(str(this_bar["close"]))

        # --- (2) FILL PENDING ORDERS ---
        next_pending: list[Order] = []
        for order in pending_orders:
            sym_bars = bar_by_ts.get(order.symbol, {})
            this_bar = sym_bars.get(ts)
            if this_bar is None:
                # Symbol didn't trade this bar; order persists
                next_pending.append(order)
                continue

            if order.order_type == OrderType.MARKET:
                fill = simulate_market_fill(order, this_bar, config)
            else:
                fill = try_fill_limit_order(order, this_bar, config)
                if fill is None:
                    next_pending.append(order)
                    continue

            # Apply the fill against the portfolio
            if fill.side == OrderSide.BUY:
                cost = fill.price * fill.quantity + fill.fee
                if cost > portfolio.cash:
                    rejected_orders.append(
                        (
                            order,
                            f"insufficient cash: need {cost:.2f}, "
                            f"have {portfolio.cash:.2f}",
                        )
                    )
                    continue
                portfolio.apply_buy(
                    order.symbol, fill.quantity, fill.price, fill.fee
                )
            else:  # SELL
                pos = portfolio.get_position(order.symbol)
                if fill.quantity > pos.quantity:
                    rejected_orders.append(
                        (
                            order,
                            f"insufficient position: trying to sell "
                            f"{fill.quantity}, have {pos.quantity}",
                        )
                    )
                    continue
                portfolio.apply_sell(
                    order.symbol, fill.quantity, fill.price, fill.fee
                )

            fills.append(fill)

        pending_orders = next_pending

        # --- (3) CALL STRATEGY ---
        # Build history slices up to and including this bar
        history: dict[str, pd.DataFrame] = {}
        for sym in strategy.symbols:
            df = bars[sym]
            history[sym] = df.loc[df.index <= ts]

        ctx = BarContext(
            ts=ts,
            symbols=list(strategy.symbols),
            history=history,
            positions=portfolio.positions_for_context(),
            cash=portfolio.cash,
        )

        try:
            strategy.on_bar(ctx)
        except Exception as e:
            log.error(
                "backtest.strategy_error ts=%s err=%s",
                ts,
                e,
                exc_info=True,
            )

        # Queue submitted orders for next bar
        pending_orders.extend(ctx.collected_orders())

        # --- (4) MARK TO MARKET ---
        positions_value = portfolio.mark_to_market(last_marks)
        equity_curve.append(
            EquityPoint(
                ts=ts,
                cash=portfolio.cash,
                positions_value=positions_value,
                total_equity=portfolio.cash + positions_value,
            )
        )

    # ----- Build result -----
    return BacktestResult(
        config=config,
        fills=fills,
        equity_curve=equity_curve,
        final_cash=portfolio.cash,
        final_positions=dict(portfolio.positions),
        rejected_orders=rejected_orders,
        strategy_state_final=dict(strategy.state),
    )
