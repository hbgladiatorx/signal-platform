"""Indicator functions over pandas Series.

Pure functions. No state, no side effects. Designed to compose cleanly with
the BarContext caching layer.

All functions return a pandas Series the same length as the input, with
leading NaN values where the indicator is undefined (e.g., the first
`period-1` values of an SMA).
"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average.

    SMA_t = mean(x[t-period+1] .. x[t])
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average using alpha = 2 / (period + 1).

    Uses adjust=False so this matches the recursive form most platforms use:
        EMA_t = alpha * x_t + (1 - alpha) * EMA_{t-1}
        EMA_0 = x_0
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    RSI = 100 - 100 / (1 + RS),  RS = avg_gain / avg_loss

    Returns NaN when there isn't enough history or when avg_loss == 0
    (the latter would produce +inf, conventionally displayed as 100).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothing is equivalent to an EMA with alpha = 1/period.
    # Pandas' .ewm(alpha=...) gives us this exactly.
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    # Where avg_loss == 0 and avg_gain > 0, RSI is conventionally 100.
    out = out.where(avg_loss != 0, 100.0)
    return out


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range.

    TR_t = max(high_t - low_t,
               |high_t - close_{t-1}|,
               |low_t  - close_{t-1}|)
    ATR_t = EMA(TR, period)  using Wilder's smoothing
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
