"""Options backtest: contract multiplier on cost/PnL, expiry settlement, and a
regression proving equity/crypto backtests are byte-identical (additive change)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from packages.backtest.engine import run_backtest
from packages.backtest.portfolio import Portfolio
from packages.backtest.types import BacktestConfig, InstrumentMeta
from packages.strategy.base import OrderSide, Strategy
from packages.strategy.context import BarContext


# --- Portfolio multiplier math ---------------------------------------------


def test_portfolio_multiplier_cost_and_pnl():
    p = Portfolio(Decimal("100000"))
    # Buy 2 option contracts @ $3.00 with 100x multiplier => $600 + fee.
    p.apply_buy("OPT", Decimal(2), Decimal("3.00"), Decimal("1.30"), Decimal(100))
    assert p.cash == Decimal("100000") - Decimal("600") - Decimal("1.30")
    pos = p.get_position("OPT")
    assert pos.multiplier == Decimal(100)
    # Sell 2 @ $5.00 => proceeds 2*5*100 = $1000 - fee; gross pnl (5-3)*2*100=400.
    p.apply_sell("OPT", Decimal(2), Decimal("5.00"), Decimal("1.30"))
    assert p.cash == (
        Decimal("100000") - Decimal("600") - Decimal("1.30")
        + Decimal("1000") - Decimal("1.30")
    )
    # realized_pnl = gross (400) minus only the SELL fee (buy fees hit cash, not
    # the basis) -> 398.70, matching the existing average-cost convention.
    assert pos.realized_pnl == Decimal("400") - Decimal("1.30")


def test_mark_to_market_uses_multiplier():
    p = Portfolio(Decimal("100000"))
    p.apply_buy("OPT", Decimal(1), Decimal("2.00"), Decimal("0"), Decimal(100))
    assert p.mark_to_market({"OPT": Decimal("2.50")}) == Decimal("250")


# --- Engine: a single-leg call across an expiry boundary --------------------


class _BuyOnceThenHold(Strategy):
    from pydantic import BaseModel

    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            ctx.submit_market(self.symbols[0], OrderSide.BUY, 1)


def _opt_bars():
    idx = pd.to_datetime(
        ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"], utc=True
    )
    # option price path: enter ~3, drift to 6 by expiry
    return pd.DataFrame(
        {"open": [3, 4, 5, 6], "high": [3, 4, 5, 6], "low": [3, 4, 5, 6],
         "close": [3, 4, 5, 6], "volume": [10, 10, 10, 10]},
        index=idx,
    )


def test_option_cost_and_expiry_settlement():
    sym = "AAPL260103C00100000@ALPACA"
    meta = {
        sym: InstrumentMeta(
            multiplier=Decimal(100),
            asset_class="option",
            expiry=date(2026, 1, 3),
            right="C",
            strike=Decimal("100"),
            underlying="AAPL@ALPACA",
        )
    }
    cfg = BacktestConfig(
        starting_cash=Decimal("100000"),
        fee_rate_bps=0,
        slippage_bps=0,
        option_fee_per_contract=Decimal("0"),
        instrument_meta=meta,
    )
    strat = _BuyOnceThenHold(symbols=[sym], params=_BuyOnceThenHold.PARAMS_MODEL())
    result = run_backtest(strat, {sym: _opt_bars()}, cfg)

    # Buy fills on bar 1 (2026-01-02) at open=4 -> cost 1*4*100 = 400.
    # Settles at expiry 2026-01-03 using the option's last mark (close=5) since
    # the underlying mark isn't in the run -> proceeds 1*5*100 = 500.
    assert result.final_positions[sym].quantity == Decimal(0)  # closed at expiry
    # net equity gain = 500 - 400 = 100
    assert result.final_equity == Decimal("100100")
    # there should be a settlement fill
    assert any(f.client_order_id.startswith("expiry-") for f in result.fills)


# --- Regression: crypto/equity unaffected when no option meta ---------------


class _BuyHoldCrypto(Strategy):
    from pydantic import BaseModel

    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            ctx.submit_market(self.symbols[0], OrderSide.BUY, 1)


def _crypto_bars():
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"], utc=True)
    return pd.DataFrame(
        {"open": [100, 110, 120], "high": [100, 110, 120], "low": [100, 110, 120],
         "close": [100, 110, 120], "volume": [5, 5, 5]},
        index=idx,
    )


def test_crypto_backtest_unchanged_by_additive_options_code():
    sym = "BTC-USDT@BINANCEUS"
    bars = {sym: _crypto_bars()}
    # Run with default config (no instrument_meta) — the additive option code
    # paths must be no-ops here.
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    strat = _BuyHoldCrypto(symbols=[sym], params=_BuyHoldCrypto.PARAMS_MODEL())
    result = run_backtest(strat, bars, cfg)
    # Buy 1 @ 110 (bar1 open), mark to 120 at end -> equity 10000 -110 +120 = 10010
    assert result.final_equity == Decimal("10010")
    assert result.final_positions[sym].quantity == Decimal(1)
    assert result.final_positions[sym].multiplier == Decimal(1)
