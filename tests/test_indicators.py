"""Tests for the indicator functions, focused on the multi-line indicators
(MACD / Bollinger / Stochastic / VWAP) added to fix the silent 0-trade class.

The headline guard: MACD's signal line is the EMA OF THE MACD LINE, so it lives
on the same scale as the MACD line and their crossover can actually flip. The
old hand/LLM bug approximated it as an SMA of price (~$3000) vs a near-zero MACD
line, making the crossover impossible — every backtest returned 0 trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from packages.strategy import indicators


def _series(values) -> pd.Series:
    return pd.Series([float(v) for v in values])


def test_macd_signal_is_ema_of_macd_line_not_price_scale():
    # A trending-then-reverting price path so MACD actually oscillates.
    prices = _series(list(range(1, 60)) + list(range(60, 1, -1)))
    out = indicators.macd(prices, fast=12, slow=26, signal=9)

    assert list(out.columns) == ["macd", "signal", "hist"]
    # signal == EMA(macd_line, 9) exactly.
    expected_signal = indicators.ema(out["macd"], 9)
    pd.testing.assert_series_equal(
        out["signal"], expected_signal, check_names=False
    )
    # Both lines are on the same (near-zero) scale — NOT price scale (~tens).
    tail = out.dropna()
    assert tail["macd"].abs().max() < 20
    assert tail["signal"].abs().max() < 20
    # hist == macd - signal
    pd.testing.assert_series_equal(
        tail["hist"], (tail["macd"] - tail["signal"]), check_names=False
    )


def test_macd_hist_changes_sign_at_a_crossover():
    # Up then down: the histogram must cross zero (a real, detectable crossover).
    prices = _series(list(range(1, 80)) + list(range(80, 1, -1)))
    hist = indicators.macd(prices)["hist"].dropna()
    assert (hist > 0).any() and (hist < 0).any()


def test_macd_rejects_bad_periods():
    s = _series(range(1, 50))
    with pytest.raises(ValueError):
        indicators.macd(s, fast=26, slow=12)  # slow must exceed fast


def test_bollinger_band_ordering_and_width():
    rng = np.random.default_rng(0)
    prices = _series(100 + rng.standard_normal(100).cumsum())
    bb = indicators.bollinger(prices, period=20, num_std=2.0)
    tail = bb.dropna()
    assert (tail["lower"] <= tail["mid"]).all()
    assert (tail["mid"] <= tail["upper"]).all()
    # Wider std → wider bands.
    wide = indicators.bollinger(prices, period=20, num_std=3.0).dropna()
    assert (wide["upper"] - wide["lower"] >= tail["upper"] - tail["lower"]).all()


def test_stochastic_bounded_0_100():
    rng = np.random.default_rng(1)
    close = 100 + rng.standard_normal(100).cumsum()
    high = pd.Series(close + 1.0)
    low = pd.Series(close - 1.0)
    st = indicators.stochastic(high, pd.Series(low), pd.Series(close), 14, 3)
    k = st["k"].dropna()
    assert (k >= 0).all() and (k <= 100).all()


def test_vwap_rolling_vs_cumulative():
    high = _series([10, 11, 12, 13, 14])
    low = _series([8, 9, 10, 11, 12])
    close = _series([9, 10, 11, 12, 13])
    volume = _series([100, 100, 100, 100, 100])
    cum = indicators.vwap(high, low, close, volume)  # period=None
    roll = indicators.vwap(high, low, close, volume, period=2)
    # Cumulative is defined from bar 0; rolling(2) has one leading NaN.
    assert not pd.isna(cum.iloc[0])
    assert pd.isna(roll.iloc[0]) and not pd.isna(roll.iloc[1])
    # With equal volume, rolling VWAP(2) == mean of the last two typical prices.
    typ = (high + low + close) / 3
    assert roll.iloc[-1] == pytest.approx((typ.iloc[-1] + typ.iloc[-2]) / 2)
