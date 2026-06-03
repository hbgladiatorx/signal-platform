"""Backtest engine — the main entry point.

`run_backtest(strategy, bars, config) -> BacktestResult`

Loop structure per bar in the unified timeline:

  1. UPDATE MARKS — record the latest closing price for any symbol that
     traded in this bar. We carry forward the last-known mark for symbols
     that didn't trade; that's needed because Binance.US sparseness means
     not every bar has every symbol.

  2. PROCESS ORDER LIFECYCLE — handle in this strict order:
     2a) EXPIRATIONS: remove orders whose expires_at_bar_count <= current
         bar count. Call strategy.on_order_expired() for each.
     2b) CANCELLATIONS: remove orders the strategy requested cancel for
         in the PREVIOUS on_bar() call. Call strategy.on_order_cancelled().
     2c) FILLS: orders queued at PRIOR bars try to fill against THIS bar's
         OHLC. Market orders fill at open + slippage. Limit orders fill if
         the bar's range crossed the limit price. With max_pct_of_volume
         set, fills are capped and remainders are requeued.
     2d) REJECTIONS: portfolio-level rejections (insufficient cash for buy,
         insufficient position for sell) call strategy.on_order_rejected().

  3. CALL STRATEGY — build a BarContext with history up to and including
     this bar's close, current positions, current cash, and a snapshot of
     pending orders. Call strategy.on_bar(). Any orders the strategy submits
     are queued for the NEXT bar. Any cancellations are recorded for the
     NEXT bar's 2b phase.

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
  config    — BacktestConfig (starting cash, fees, slippage, volume cap)

Returns:
  BacktestResult with fills, equity_curve, final positions,
  rejected/cancelled/expired order records.

Limitations (Phase 2):
  - Long-only
  - No margin
  - Sequential / single-threaded
"""
from __future__ import annotations

import dataclasses
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
    InstrumentMeta,
)
from packages.strategy.base import Order, OrderSide, OrderType, Strategy
from packages.strategy.context import BarContext

log = logging.getLogger(__name__)


def _option_settlement_price(
    meta: InstrumentMeta, symbol: str, last_marks: dict[str, Decimal]
) -> Decimal:
    """Settlement price for an expiring option: intrinsic value vs the
    underlying mark when known, else the option's last mark, else worthless."""
    if meta.underlying and meta.strike is not None and meta.right:
        underlying = last_marks.get(meta.underlying)
        if underlying is not None:
            if meta.right.upper() == "C":
                return max(Decimal(0), underlying - meta.strike)
            return max(Decimal(0), meta.strike - underlying)
    last = last_marks.get(symbol)
    return last if last is not None else Decimal(0)


def _settle_expiring_options(
    ts: pd.Timestamp,
    bar_count: int,
    portfolio: Portfolio,
    config: BacktestConfig,
    last_marks: dict[str, Decimal],
    fills: list[Fill],
    settled: set[str],
) -> None:
    if not config.instrument_meta:
        return
    today = ts.date() if hasattr(ts, "date") else ts
    for sym, pos in list(portfolio.positions.items()):
        if pos.quantity == 0 or sym in settled:
            continue
        meta = config.instrument_meta.get(sym)
        if meta is None or meta.asset_class != "option" or meta.expiry is None:
            continue
        if today < meta.expiry:
            continue
        settle_price = _option_settlement_price(meta, sym, last_marks)
        qty = pos.quantity
        # Settlement/exercise carries no commission in this model.
        portfolio.apply_sell(sym, qty, settle_price, Decimal(0))
        fills.append(
            Fill(
                client_order_id=f"expiry-{sym}-{bar_count}",
                symbol=sym,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=qty,
                price=settle_price,
                fee=Decimal(0),
                filled_ts=ts,
                order_submitted_ts=ts,
                is_partial=False,
            )
        )
        settled.add(sym)


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


def _safe_callback(callback: Any, *args: Any, **kwargs: Any) -> None:
    """Invoke a strategy callback, swallowing exceptions with a log entry.

    A buggy strategy callback shouldn't crash the backtest. The error is
    logged so the strategy author can diagnose it.
    """
    try:
        callback(*args, **kwargs)
    except Exception as e:
        log.error(
            "backtest.strategy_callback_error fn=%s err=%s",
            getattr(callback, "__name__", "<unknown>"),
            e,
            exc_info=True,
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

    # Static snapshot of option contracts in this run, exposed to strategies via
    # ctx.option_chain(). Empty unless option instrument_meta was supplied.
    option_chain_snapshot: list[dict[str, Any]] = [
        {
            "symbol": s,
            "underlying": m.underlying,
            "right": m.right,
            "strike": float(m.strike) if m.strike is not None else None,
            "expiry": str(m.expiry) if m.expiry is not None else None,
            "multiplier": float(m.multiplier),
        }
        for s, m in (config.instrument_meta or {}).items()
        if m.asset_class == "option"
    ]

    fills: list[Fill] = []
    equity_curve: list[EquityPoint] = []
    rejected_orders: list[tuple[Order, str]] = []
    cancelled_orders: list[Order] = []
    expired_orders: list[Order] = []
    pending_orders: list[Order] = []
    last_marks: dict[str, Decimal] = {}
    settled_options: set[str] = set()

    # Cancellation requests collected during the PREVIOUS on_bar(), to be
    # processed at the start of THIS bar's Phase 2.
    pending_cancellations: set[str] = set()

    # ----- Walk timeline -----
    for bar_count, ts in enumerate(timeline):
        # --- (1) UPDATE MARKS ---
        for sym in strategy.symbols:
            this_bar = bar_by_ts.get(sym, {}).get(ts)
            if this_bar is not None:
                last_marks[sym] = Decimal(str(this_bar["close"]))

        # --- (1b) OPTION EXPIRY SETTLEMENT ---
        # Force-close any open option position whose expiry date has been
        # reached, settling at intrinsic value vs the underlying (if its mark is
        # known) else the option's last mark, else worthless. No-op unless the
        # backtest was given option instrument_meta.
        _settle_expiring_options(
            ts, bar_count, portfolio, config, last_marks, fills, settled_options
        )

        # --- (2a) EXPIRATIONS ---
        # Remove orders whose expiry has been reached.
        surviving_after_expiry: list[Order] = []
        for order in pending_orders:
            if (
                order.expires_at_bar_count is not None
                and bar_count >= order.expires_at_bar_count
            ):
                expired_orders.append(order)
                _safe_callback(strategy.on_order_expired, order)
            else:
                surviving_after_expiry.append(order)
        pending_orders = surviving_after_expiry

        # --- (2b) CANCELLATIONS ---
        # Process cancel requests from the previous on_bar() call.
        if pending_cancellations:
            surviving_after_cancel: list[Order] = []
            for order in pending_orders:
                if order.client_order_id in pending_cancellations:
                    cancelled_orders.append(order)
                    _safe_callback(strategy.on_order_cancelled, order)
                else:
                    surviving_after_cancel.append(order)
            pending_orders = surviving_after_cancel
            pending_cancellations = set()  # consumed

        # --- (2c) FILL REMAINING PENDING ORDERS ---
        next_pending: list[Order] = []
        for order in pending_orders:
            sym_bars = bar_by_ts.get(order.symbol, {})
            this_bar = sym_bars.get(ts)
            if this_bar is None:
                # Symbol didn't trade this bar; order persists
                next_pending.append(order)
                continue

            if order.order_type == OrderType.MARKET:
                fill_result = simulate_market_fill(order, this_bar, config)
            else:
                fill_result = try_fill_limit_order(order, this_bar, config)

            if fill_result is None:
                # No fill this bar (limit not crossed, or zero volume)
                next_pending.append(order)
                continue

            fill, remainder_qty = fill_result

            # --- (2d) Apply fill against portfolio; REJECT if insufficient ---
            if fill.side == OrderSide.BUY:
                mult = config.multiplier_for(order.symbol)
                cost = fill.price * fill.quantity * mult + fill.fee
                if cost > portfolio.cash:
                    reason = (
                        f"insufficient cash: need {cost:.2f}, "
                        f"have {portfolio.cash:.2f}"
                    )
                    rejected_orders.append((order, reason))
                    _safe_callback(strategy.on_order_rejected, order, reason)
                    continue
                portfolio.apply_buy(
                    order.symbol, fill.quantity, fill.price, fill.fee, mult
                )
            else:  # SELL
                pos = portfolio.get_position(order.symbol)
                if fill.quantity > pos.quantity:
                    reason = (
                        f"insufficient position: trying to sell "
                        f"{fill.quantity}, have {pos.quantity}"
                    )
                    rejected_orders.append((order, reason))
                    _safe_callback(strategy.on_order_rejected, order, reason)
                    continue
                portfolio.apply_sell(
                    order.symbol, fill.quantity, fill.price, fill.fee
                )

            fills.append(fill)

            # If only partially filled, requeue the remainder with the SAME
            # client_order_id so strategy can track total filled vs original.
            if remainder_qty > 0:
                remainder_order = dataclasses.replace(
                    order, quantity=remainder_qty
                )
                next_pending.append(remainder_order)

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
            pending_orders=pending_orders,
            bar_count=bar_count,
            option_chain=option_chain_snapshot,
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
        # Carry cancellation requests to next bar's Phase 2b
        pending_cancellations = ctx.collected_cancellations()

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
        cancelled_orders=cancelled_orders,
        expired_orders=expired_orders,
        strategy_state_final=dict(strategy.state),
    )
