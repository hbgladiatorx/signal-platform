"""Tests for the BarContext multi-line indicator accessors and the stateless
crossover helpers — the framework surface that lets MACD/Bollinger/Stochastic
strategies trade correctly instead of silently returning 0 trades.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from packages.strategy.context import BarContext
from packages.strategy.num import FlexDecimal


def _ctx(close, *, high=None, low=None, volume=None, symbol="ETH-USDT@BINANCEUS"):
    """Build a BarContext whose history for `symbol` is the given close path."""
    n = len(close)
    high = high if high is not None else [c + 1 for c in close]
    low = low if low is not None else [c - 1 for c in close]
    volume = volume if volume is not None else [100] * n
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
    return BarContext(
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbols=[symbol],
        history={symbol: df},
        positions={},
        cash=Decimal("25000"),
    )


SYM = "ETH-USDT@BINANCEUS"


def test_macd_returns_flexdecimal_fields():
    prices = list(range(1, 60)) + list(range(60, 1, -1))
    m = _ctx(prices).macd(SYM)
    assert m is not None
    for v in (m.macd, m.signal, m.hist):
        assert isinstance(v, FlexDecimal)
    assert isinstance(m.crossed_up, bool) and isinstance(m.crossed_down, bool)
    # signal and macd are on the same near-zero scale (not price scale).
    assert abs(m.macd) < 20 and abs(m.signal) < 20


def test_macd_none_on_short_history():
    assert _ctx(list(range(1, 10))).macd(SYM) is None


def test_macd_detects_bearish_cross_at_the_peak():
    # Rising into a peak then falling: at the turn the histogram goes negative,
    # i.e. a bearish (signal-over-macd) crossover should register.
    up = list(range(1, 80))
    down = list(range(80, 1, -1))
    full = up + down
    saw_cross_down = False
    # Scan every possible "current bar" from the first computable one onward so
    # we land on the exact bar where the histogram flips negative at the peak.
    for cut in range(35, len(full) + 1):
        m = _ctx(full[:cut]).macd(SYM)
        if m is not None and m.crossed_down:
            saw_cross_down = True
            break
    assert saw_cross_down


def test_crossed_above_detects_ema_golden_cross():
    # Flat-low then a sharp ramp pulls the fast EMA up through the slow EMA.
    prices = [100] * 40 + [100 + 3 * i for i in range(1, 20)]
    saw = any(
        _ctx(prices[:cut]).crossed_above(SYM, 5, 20, kind="ema")
        for cut in range(25, len(prices) + 1)
    )
    assert saw


def test_crossed_below_mirror():
    prices = [100] * 40 + [100 - 3 * i for i in range(1, 20)]
    saw = any(
        _ctx(prices[:cut]).crossed_below(SYM, 5, 20, kind="ema")
        for cut in range(25, len(prices) + 1)
    )
    assert saw


def test_crossed_above_none_on_short_history():
    assert _ctx([1, 2, 3]).crossed_above(SYM, 5, 20) is None


def test_bollinger_and_stoch_and_vwap_accessors():
    prices = [100 + (i % 7) for i in range(60)]
    ctx = _ctx(prices)
    b = ctx.bollinger(SYM, period=20)
    assert b is not None and b.lower <= b.mid <= b.upper
    s = ctx.stoch(SYM, k_period=14, d_period=3)
    assert s is not None and Decimal("0") <= s.k <= Decimal("100")
    v = ctx.vwap(SYM, period=20)
    assert v is not None and isinstance(v, FlexDecimal)
