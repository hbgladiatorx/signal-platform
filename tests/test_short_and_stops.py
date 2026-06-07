"""Tests for the new engine capabilities: shorting + margin, native stop /
trailing-stop orders, and short round-trip analytics.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest
from pydantic import BaseModel

from packages.backtest.analytics import compute_analytics
from packages.backtest.engine import run_backtest
from packages.backtest.fills import try_fill_stop_order
from packages.backtest.portfolio import Portfolio
from packages.backtest.types import BacktestConfig
from packages.strategy.base import Order, OrderSide, OrderType, Strategy
from packages.strategy.context import BarContext

SYM = "ETH-USDT@BINANCEUS"


def _bars(prices):
    idx = pd.date_range("2026-01-01", periods=len(prices), freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": prices, "high": [p * 1.01 for p in prices],
         "low": [p * 0.99 for p in prices], "close": prices,
         "volume": [1_000_000] * len(prices)},
        index=idx,
    )


# ---------------- Portfolio: short accounting ----------------
def test_portfolio_short_then_cover_realizes_pnl():
    p = Portfolio(Decimal("10000"))
    p.apply_fill("X", OrderSide.SELL, Decimal(10), Decimal(100), Decimal(0))
    assert p.cash == Decimal("11000")              # received proceeds
    assert p.get_position("X").quantity == Decimal(-10)
    assert p.cash + p.mark_to_market({"X": Decimal(95)}) == Decimal("10050")
    p.apply_fill("X", OrderSide.BUY, Decimal(10), Decimal(90), Decimal(0))
    assert p.get_position("X").quantity == Decimal(0)
    assert p.get_position("X").realized_pnl == Decimal("100")  # shorted high, covered low


def test_portfolio_flip_long_to_short():
    p = Portfolio(Decimal("10000"))
    p.apply_fill("X", OrderSide.BUY, Decimal(10), Decimal(100), Decimal(0))   # long 10
    p.apply_fill("X", OrderSide.SELL, Decimal(15), Decimal(110), Decimal(0))  # close 10, short 5
    pos = p.get_position("X")
    assert pos.quantity == Decimal(-5)
    assert pos.avg_cost == Decimal(110)             # residual short opened at 110
    assert pos.realized_pnl == Decimal("100")       # (110-100)*10 on the closed long


# ---------------- Engine: short strategy end-to-end ----------------
class _ShortOnce(Strategy):
    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            ctx.submit_sell_market(SYM, 10)        # open short while flat
        elif ctx.bar_count == 3:
            ctx.submit_buy_market(SYM, 10)         # cover


def test_engine_short_profits_when_price_falls():
    cfg = BacktestConfig(starting_cash=Decimal("100000"), fee_rate_bps=0, slippage_bps=0)
    # Price falls 100 -> 70: a short should profit.
    result = run_backtest(_ShortOnce(symbols=[SYM], params=_ShortOnce.PARAMS_MODEL()),
                          {SYM: _bars([100, 90, 80, 70, 70])}, cfg)
    assert result.orders_submitted == 2
    assert result.final_positions[SYM].quantity == Decimal(0)
    # Short 10 @100 (fills next bar open=90), cover 10 @70 -> profit > 0.
    assert result.final_equity > Decimal("100000")


def test_engine_rejects_short_when_disabled():
    cfg = BacktestConfig(starting_cash=Decimal("100000"), fee_rate_bps=0,
                         slippage_bps=0, allow_short=False)
    result = run_backtest(_ShortOnce(symbols=[SYM], params=_ShortOnce.PARAMS_MODEL()),
                          {SYM: _bars([100, 90, 80, 70, 70])}, cfg)
    assert result.final_positions.get(SYM, None) is None or \
        result.final_positions[SYM].quantity == Decimal(0)
    assert any("shorting disabled" in r for _, r in result.rejected_orders)


def test_engine_margin_blocks_oversized_buy():
    # margin_rate=1.0 (default) means no leverage: can't deploy more than equity.
    class _Greedy(Strategy):
        class PARAMS_MODEL(BaseModel):  # noqa: D106
            pass

        def on_bar(self, ctx: BarContext) -> None:
            if ctx.bar_count == 0:
                ctx.submit_buy_market(SYM, 1000)   # ~$100k notional on $10k acct

    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    result = run_backtest(_Greedy(symbols=[SYM], params=_Greedy.PARAMS_MODEL()),
                          {SYM: _bars([100, 100, 100])}, cfg)
    assert any("buying power" in r for _, r in result.rejected_orders)


# ---------------- fills: native stop + trailing ----------------
def _bar(o, h, l, c, v=1_000_000):
    return pd.Series({"open": o, "high": h, "low": l, "close": c, "volume": v},
                     name=pd.Timestamp("2026-01-02", tz="UTC"))


def test_sell_stop_triggers_on_breach():
    cfg = BacktestConfig(fee_rate_bps=0, slippage_bps=0)
    order = Order(SYM, OrderSide.SELL, Decimal(10), OrderType.STOP, None,
                  pd.Timestamp("2026-01-01", tz="UTC"), "o1", stop_price=Decimal(95))
    # Bar trades down to 94 (low) -> sell stop at 95 triggers.
    res = try_fill_stop_order(order, _bar(98, 99, 94, 96), cfg, {})
    assert res is not None
    fill, rem = res
    assert rem == 0 and fill.price == Decimal(95)  # filled at stop (no gap)
    # A bar that never reaches 95 -> no trigger.
    assert try_fill_stop_order(order, _bar(98, 99, 96, 97), cfg, {}) is None


def test_sell_stop_gap_fills_at_open():
    cfg = BacktestConfig(fee_rate_bps=0, slippage_bps=0)
    order = Order(SYM, OrderSide.SELL, Decimal(10), OrderType.STOP, None,
                  pd.Timestamp("2026-01-01", tz="UTC"), "o1", stop_price=Decimal(95))
    # Gap down: opens at 90 (below the 95 stop) -> fills at the worse open price.
    fill, _ = try_fill_stop_order(order, _bar(90, 92, 88, 91), cfg, {})
    assert fill.price == Decimal(90)


def test_trailing_stop_ratchets_then_triggers():
    cfg = BacktestConfig(fee_rate_bps=0, slippage_bps=0)
    order = Order(SYM, OrderSide.SELL, Decimal(10), OrderType.TRAILING_STOP, None,
                  pd.Timestamp("2026-01-01", tz="UTC"), "t1", trail_percent=Decimal(10))
    state: dict = {}
    # Bar 1 high 100 -> stop trails to 90; low 96 doesn't breach.
    assert try_fill_stop_order(order, _bar(98, 100, 96, 99), cfg, state) is None
    assert state["t1"] == Decimal(100)
    # Bar 2 high 120 -> stop ratchets up to 108; low 110 doesn't breach.
    assert try_fill_stop_order(order, _bar(100, 120, 110, 118), cfg, state) is None
    assert state["t1"] == Decimal(120)
    # Bar 3 falls to 107 (< 108) -> triggers.
    res = try_fill_stop_order(order, _bar(115, 116, 107, 108), cfg, state)
    assert res is not None


# ---------------- analytics: short round trip labelled correctly ----------------
def test_short_round_trip_analytics():
    cfg = BacktestConfig(starting_cash=Decimal("100000"), fee_rate_bps=0, slippage_bps=0)
    result = run_backtest(_ShortOnce(symbols=[SYM], params=_ShortOnce.PARAMS_MODEL()),
                          {SYM: _bars([100, 90, 80, 70, 70])}, cfg)
    m = compute_analytics(result)
    assert m.num_closed_trades == 1
    rt = m.closed_round_trips[0]
    assert rt.side == "short"
    assert rt.duration_seconds > 0          # entry (short) precedes exit (cover)
    assert rt.net_pnl > 0
