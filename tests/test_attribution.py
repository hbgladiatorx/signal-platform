"""Attribution: signal emission -> order/fill tags -> round-trip entry_tags ->
per-symbol and per-signal P&L decomposition. Also verifies the additive change
leaves a no-signal backtest's results untouched.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
from pydantic import BaseModel

import json

from packages.backtest.analytics import compute_analytics
from packages.backtest.attribution import attribution_to_dict, compute_attribution
from packages.backtest.engine import run_backtest
from packages.backtest.types import BacktestConfig
from packages.strategy.base import OrderSide, Strategy
from packages.strategy.context import BarContext


# --- Strategies -------------------------------------------------------------


class _TaggedTwoSymbol(Strategy):
    """Buy both symbols on bar 0 tagged 'trend' (after a blocked 'cooldown'
    filter), sell both on bar 2 tagged 'tp'."""

    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            for s in self.symbols:
                # A blocked filter: logged, but must NOT tag the order.
                ctx.signal("cooldown", passed=False, symbol=s)
                ctx.signal("trend", value=ctx.close(s), symbol=s)
                ctx.submit_buy_market(s, 1)
        elif ctx.bar_count == 2:
            for s in self.symbols:
                ctx.signal("tp", symbol=s)
                ctx.submit_sell_market(s, 1)


def _bars(opens: list[int]) -> pd.DataFrame:
    idx = pd.to_datetime(
        [f"2026-01-0{i + 1}" for i in range(len(opens))], utc=True
    )
    return pd.DataFrame(
        {"open": opens, "high": opens, "low": opens, "close": opens,
         "volume": [10] * len(opens)},
        index=idx,
    )


def _run_two_symbol():
    win, lose = "WIN@X", "LOSE@X"
    bars = {
        # buy fills bar1 @110, sell fills bar3 @130 -> +20
        win: _bars([100, 110, 120, 130]),
        # buy fills bar1 @95, sell fills bar3 @85 -> -10
        lose: _bars([100, 95, 90, 85]),
    }
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    strat = _TaggedTwoSymbol(symbols=[win, lose], params=_TaggedTwoSymbol.PARAMS_MODEL())
    result = run_backtest(strat, bars, cfg)
    return win, lose, result


# --- Tag propagation --------------------------------------------------------


def test_blocked_filter_logged_but_not_tagged():
    win, lose, result = _run_two_symbol()
    # 'cooldown' was emitted passed=False for each symbol -> 2 events, no tags.
    cooldowns = [e for e in result.signal_events if e.name == "cooldown"]
    assert len(cooldowns) == 2
    assert all(e.passed is False for e in cooldowns)
    for f in result.fills:
        assert "cooldown" not in f.tags


def test_entry_fills_tagged_with_entry_signal_only():
    win, lose, result = _run_two_symbol()
    buys = [f for f in result.fills if f.side == OrderSide.BUY]
    sells = [f for f in result.fills if f.side == OrderSide.SELL]
    assert buys and sells
    # Entries carry 'trend' (not the exit tag, not the blocked filter).
    for f in buys:
        assert f.tags == ("trend",)
    for f in sells:
        assert f.tags == ("tp",)


def test_per_symbol_signal_scoping():
    """A signal emitted for symbol WIN must not tag LOSE's order in the same bar."""
    win, lose, result = _run_two_symbol()
    win_buy = next(f for f in result.fills if f.symbol == win and f.side == OrderSide.BUY)
    lose_buy = next(f for f in result.fills if f.symbol == lose and f.side == OrderSide.BUY)
    assert win_buy.tags == ("trend",)
    assert lose_buy.tags == ("trend",)  # each tagged from its OWN trend signal


# --- Round-trip entry_tags --------------------------------------------------


def test_round_trip_entry_tags():
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    assert len(analytics.closed_round_trips) == 2
    for rt in analytics.closed_round_trips:
        assert rt.entry_tags == ("trend",)


# --- Attribution decomposition ----------------------------------------------


def test_by_symbol_attribution():
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    attr = compute_attribution(result, analytics)

    assert attr.total_net_pnl == Decimal("10")  # +20 - 10
    assert attr.best_symbol == win
    assert attr.worst_symbol == lose

    by_sym = {s.symbol: s for s in attr.by_symbol}
    assert by_sym[win].net_pnl == Decimal("20")
    assert by_sym[win].wins == 1 and by_sym[win].losses == 0
    assert by_sym[win].win_rate_pct == 100.0
    assert by_sym[lose].net_pnl == Decimal("-10")
    # Share of total: 20/10 = 200%, -10/10 = -100%.
    assert by_sym[win].pct_of_total_net_pnl == 200.0
    assert by_sym[lose].pct_of_total_net_pnl == -100.0


def test_by_signal_attribution():
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    attr = compute_attribution(result, analytics)

    by_sig = {s.name: s for s in attr.by_signal}
    # 'trend' tagged both entries -> 2 trades, net = +20 - 10 = +10.
    assert by_sig["trend"].num_trades == 2
    assert by_sig["trend"].net_pnl == Decimal("10")
    assert by_sig["trend"].num_fired == 2
    assert by_sig["trend"].num_blocked == 0

    # 'tp' was an EXIT tag -> attributes no trades, but its firing is logged.
    assert by_sig["tp"].num_trades == 0
    assert by_sig["tp"].num_fired == 2

    # 'cooldown' only ever blocked -> visible for filter analysis.
    assert by_sig["cooldown"].num_blocked == 2
    assert by_sig["cooldown"].num_fired == 0
    assert by_sig["cooldown"].num_trades == 0
    assert by_sig["cooldown"].block_rate_pct == 100.0


# --- No-signal regression ---------------------------------------------------


class _BuyHoldNoSignals(Strategy):
    class PARAMS_MODEL(BaseModel):  # noqa: D106
        pass

    def on_bar(self, ctx: BarContext) -> None:
        if ctx.bar_count == 0:
            ctx.submit_buy_market(self.symbols[0], 1)


def test_no_signal_strategy_has_empty_signal_attribution():
    sym = "BTC-USDT@BINANCEUS"
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=0, slippage_bps=0)
    strat = _BuyHoldNoSignals(symbols=[sym], params=_BuyHoldNoSignals.PARAMS_MODEL())
    result = run_backtest(strat, {sym: _bars([100, 110, 120])}, cfg)

    assert result.signal_events == []
    for f in result.fills:
        assert f.tags == ()

    analytics = compute_analytics(result)
    attr = compute_attribution(result, analytics)
    assert attr.by_signal == []
    # The open position never closed -> no closed trips, nothing to attribute.
    assert attr.num_closed_trades == 0
    assert attr.untagged_trades == 0


# --- Serialization (JSONB persistence / API shape) --------------------------


def test_attribution_to_dict_is_json_safe_and_lossless():
    win, lose, result = _run_two_symbol()
    analytics = compute_analytics(result)
    attr = compute_attribution(result, analytics)

    d = attribution_to_dict(attr)
    # Round-trips through JSON unchanged (no Decimal/other unserializable types).
    assert json.loads(json.dumps(d)) == d

    # Money is carried as strings to preserve precision; ratios stay numeric.
    assert d["total_net_pnl"] == "10"
    by_sym = {s["symbol"]: s for s in d["by_symbol"]}
    assert by_sym[win]["net_pnl"] == "20"
    assert by_sym[win]["pct_of_total_net_pnl"] == 200.0

    by_sig = {s["name"]: s for s in d["by_signal"]}
    assert by_sig["trend"]["net_pnl"] == "10"
    assert by_sig["trend"]["num_trades"] == 2
    assert by_sig["cooldown"]["block_rate_pct"] == 100.0
    assert by_sig["cooldown"]["num_evaluated"] == 2
    assert d["best_symbol"] == win and d["worst_symbol"] == lose
