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


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Moving Average Convergence Divergence.

    macd_line   = EMA(fast) - EMA(slow)
    signal_line = EMA(macd_line, signal)
    hist        = macd_line - signal_line

    Returns a DataFrame with columns ``macd``, ``signal``, ``hist`` aligned to
    the input index (leading NaN until enough history). The signal line is an
    EMA OF THE MACD LINE — not an SMA of price. (Approximating it with a price
    SMA, as hand/LLM-written code has done, makes ``signal`` ~price-scale and
    ``macd`` ~zero-scale, so the crossover can never flip — a silent 0-trade
    bug. This is the canonical, comparable-units definition.)
    """
    if fast < 1 or slow < 1 or signal < 1:
        raise ValueError("macd periods must be >= 1")
    if slow <= fast:
        raise ValueError(f"slow ({slow}) must exceed fast ({fast})")
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist}
    )


def bollinger(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands.

    mid   = SMA(period)
    upper = mid + num_std * rolling_std(period)
    lower = mid - num_std * rolling_std(period)

    Returns a DataFrame with columns ``upper``, ``mid``, ``lower``. Uses the
    population std (ddof=0) to match the convention used by most charting
    platforms.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    mid = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {"upper": mid + num_std * std, "mid": mid, "lower": mid - num_std * std}
    )


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """Stochastic oscillator (%K and %D), each in 0..100.

    %K = 100 * (close - lowest_low) / (highest_high - lowest_low)  over k_period
    %D = SMA(%K, d_period)

    Where the high/low range is zero (flat market) %K is NaN; downstream None
    checks skip those bars.
    """
    if k_period < 1 or d_period < 1:
        raise ValueError("stochastic periods must be >= 1")
    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    rng = highest - lowest
    percent_k = 100 * (close - lowest) / rng.where(rng != 0)
    percent_d = percent_k.rolling(window=d_period, min_periods=d_period).mean()
    return pd.DataFrame({"k": percent_k, "d": percent_d})


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int | None = None,
) -> pd.Series:
    """Volume-Weighted Average Price over the typical price (H+L+C)/3.

    With ``period`` set, a rolling VWAP over the last ``period`` bars (the shape
    the builder's ``vwap {period}`` node emits). With ``period`` None, a
    cumulative VWAP from the start of the series. Bars with zero rolling volume
    yield NaN.
    """
    typical = (high + low + close) / 3
    pv = typical * volume
    if period is None:
        cum_vol = volume.cumsum()
        return pv.cumsum() / cum_vol.where(cum_vol != 0)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    roll_pv = pv.rolling(window=period, min_periods=period).sum()
    roll_vol = volume.rolling(window=period, min_periods=period).sum()
    return roll_pv / roll_vol.where(roll_vol != 0)
