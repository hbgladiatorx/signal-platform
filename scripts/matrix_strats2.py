"""50-strategy x ticker x timeframe matrix -- ROUND 2 (all-new archetypes).

Same harness/costs/window-sizing as matrix_strats.py, but 50 DISTINCT strategy
families NOT covered in round 1. Round 1 was trend-MA cross, price-vs-MA, MACD,
ROC, RSI-MR, stochastic, bollinger fade/breakout, vwap, donchian, ATR bands,
combos. Round 2 deliberately avoids all of those and instead spans ~22 new
indicator families, all computed directly from the OHLCV frame:

  Williams %R, CCI, CMO, MFI, StochRSI, z-score, Bollinger %B, DPO,
  ADX/DMI, Vortex, Aroon, Supertrend, Heikin-Ashi, OBV, Force Index,
  TRIX, Awesome Osc, Ultimate Osc, Fisher transform, Coppock curve,
  Elder-Ray, and the DEMA/TEMA/HMA/WMA/KAMA moving-average zoo.

  docker compose run --rm -d -w /app --name m_strats2 \
    -e MATRIX_OUT=/app/logs/matrix_strats2.jsonl \
    -v /home/signal/app/scripts/matrix_strats2.py:/tmp/ms2.py \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python /tmp/ms2.py

Knobs: MATRIX_TF (default "5m,15m"), MATRIX_SYMBOLS (default top-8),
MATRIX_MAX_CELLS, MATRIX_OUT. Results stream one row per (tf, symbol, strategy).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
from pydantic import BaseModel

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext

WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
_ALL_TF = {
    "5m": datetime(2026, 5, 15, tzinfo=timezone.utc),   # ~1 month
    "15m": datetime(2026, 3, 15, tzinfo=timezone.utc),  # ~3 months
}
_sel = os.environ.get("MATRIX_TF", "5m,15m").split(",")
TIMEFRAMES = [(tf, _ALL_TF[tf]) for tf in _sel if tf in _ALL_TF]
DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]
QUOTE = "-USDT@BINANCEUS"
OUT_PATH = os.environ.get("MATRIX_OUT", "/app/logs/matrix_strats2.jsonl")


# ----------------------------- sizing helpers ----------------------------
def _enter_full(ctx: BarContext, symbol: str) -> None:
    price = ctx.close(symbol)
    if price is None or float(price) <= 0:
        return
    qty = (float(ctx.cash) * 0.95) / float(price)
    if qty > 0:
        ctx.submit_buy_market(symbol, qty)


def _exit_full(ctx: BarContext, symbol: str) -> None:
    pos = ctx.position(symbol)
    if float(pos) > 0:
        ctx.submit_sell_market(symbol, pos)


# ----------------------------- tail accessor -----------------------------
# Each on_bar recomputes from a bounded tail (keeps cost ~O(window) per bar,
# not O(history)). Window is sized per-strategy to its longest lookback.
def _t(ctx: BarContext, s: str, k: int):
    df = ctx.bars(s)
    if df is None or len(df) < max(k, 3):
        return None
    return df.iloc[-k:]


def _np(t, col):
    return t[col].to_numpy(dtype=float)


# ------------------------- indicator primitives --------------------------
def _ema_s(x: np.ndarray, n: int) -> pd.Series:
    return pd.Series(x).ewm(span=n, adjust=False).mean()


def _wma_last(x: np.ndarray, n: int):
    if len(x) < n:
        return None
    w = np.arange(1, n + 1, dtype=float)
    return float(np.dot(x[-n:], w) / w.sum())


def _dema_last(x: np.ndarray, n: int):
    if len(x) < n:
        return None
    e = _ema_s(x, n)
    e2 = e.ewm(span=n, adjust=False).mean()
    return float((2 * e - e2).iloc[-1])


def _tema_last(x: np.ndarray, n: int):
    if len(x) < n:
        return None
    e = _ema_s(x, n)
    e2 = e.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return float((3 * e - 3 * e2 + e3).iloc[-1])


def _wma_at(x: np.ndarray, p: int, end: int):  # WMA of window ending at index `end`
    w = np.arange(1, p + 1, dtype=float)
    return float(np.dot(x[end - p + 1:end + 1], w) / w.sum())


def _hma_last(x: np.ndarray, n: int):
    half, sq = max(n // 2, 1), max(int(round(np.sqrt(n))), 1)
    if len(x) < n + sq:
        return None
    # HMA last value only: need the last `sq` raw points, each from two WMAs.
    raw = np.array([2 * _wma_at(x, half, e) - _wma_at(x, n, e)
                    for e in range(len(x) - sq, len(x))])
    w = np.arange(1, sq + 1, dtype=float)
    return float(np.dot(raw, w) / w.sum())


def _kama_last(x: np.ndarray, n: int, fast: int = 2, slow: int = 30):
    if len(x) < n + 2:
        return None
    s = pd.Series(x)
    change = (s - s.shift(n)).abs()
    vol = s.diff().abs().rolling(n).sum()
    er = (change / vol).fillna(0.0)
    sc = (er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2
    kama = np.full(len(s), np.nan)
    kama[n] = s.iloc[n]
    for i in range(n + 1, len(s)):
        kama[i] = kama[i - 1] + sc.iloc[i] * (s.iloc[i] - kama[i - 1])
    return float(kama[-1])


def _williams_r(t, n):
    if t is None or len(t) < n:
        return None
    hh = t["high"].iloc[-n:].max()
    ll = t["low"].iloc[-n:].min()
    c = t["close"].iloc[-1]
    return None if hh == ll else float(-100 * (hh - c) / (hh - ll))


def _cci(t, n):
    if t is None or len(t) < n:
        return None
    tp = ((t["high"] + t["low"] + t["close"]) / 3).iloc[-n:]
    m = tp.mean()
    md = (tp - m).abs().mean()
    return None if md == 0 else float((tp.iloc[-1] - m) / (0.015 * md))


def _cmo(t, n):
    if t is None or len(t) < n + 1:
        return None
    d = t["close"].diff().iloc[-n:]
    up = d.clip(lower=0).sum()
    dn = (-d.clip(upper=0)).sum()
    return None if (up + dn) == 0 else float(100 * (up - dn) / (up + dn))


def _mfi(t, n):
    if t is None or len(t) < n + 1:
        return None
    tp = (t["high"] + t["low"] + t["close"]) / 3
    mf = tp * t["volume"]
    dtp = tp.diff()
    pos = mf.where(dtp > 0, 0.0).iloc[-n:].sum()
    neg = mf.where(dtp < 0, 0.0).iloc[-n:].sum()
    if neg == 0:
        return 100.0
    return float(100 - 100 / (1 + pos / neg))


def _stochrsi(t, n):  # returns 0..1
    if t is None or len(t) < n * 2:
        return None
    delta = t["close"].diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    w = rsi.iloc[-n:]
    lo, hi = w.min(), w.max()
    return None if hi == lo else float((rsi.iloc[-1] - lo) / (hi - lo))


def _zscore(t, n):
    if t is None or len(t) < n:
        return None
    c = t["close"].iloc[-n:]
    sd = c.std()
    return None if sd == 0 else float((c.iloc[-1] - c.mean()) / sd)


def _percent_b(t, n, k=2.0):
    if t is None or len(t) < n:
        return None
    c = t["close"].iloc[-n:]
    m, sd = c.mean(), c.std()
    lower, upper = m - k * sd, m + k * sd
    return None if upper == lower else float((c.iloc[-1] - lower) / (upper - lower))


def _dpo(t, n):
    if t is None or len(t) < n + n // 2 + 1:
        return None
    sma = t["close"].rolling(n).mean()
    shift = n // 2 + 1
    return float(t["close"].iloc[-1] - sma.iloc[-1 - shift])


def _adx(t, n):  # -> (pdi, mdi, adx)
    if t is None or len(t) < n * 3:
        return None
    h, l, c = t["high"], t["low"], t["close"]
    up = h.diff()
    dn = -l.diff()
    plus = ((up > dn) & (up > 0)).astype(float) * up
    minus = ((dn > up) & (dn > 0)).astype(float) * dn
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return float(pdi.iloc[-1]), float(mdi.iloc[-1]), float(adx.iloc[-1])


def _vortex(t, n):  # -> (vi_plus, vi_minus)
    if t is None or len(t) < n + 1:
        return None
    h, l, c = t["high"], t["low"], t["close"]
    vmp = (h - l.shift()).abs()
    vmm = (l - h.shift()).abs()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    str_ = tr.iloc[-n:].sum()
    if str_ == 0:
        return None
    return float(vmp.iloc[-n:].sum() / str_), float(vmm.iloc[-n:].sum() / str_)


def _aroon(t, n):  # -> (up, down)
    if t is None or len(t) < n + 1:
        return None
    hw = t["high"].iloc[-(n + 1):]
    lw = t["low"].iloc[-(n + 1):]
    since_high = n - int(np.argmax(hw.to_numpy()))
    since_low = n - int(np.argmin(lw.to_numpy()))
    return float(100 * (n - since_high) / n), float(100 * (n - since_low) / n)


def _supertrend_dir(t, n, mult):  # -> (dir_now, dir_prev) in {+1,-1}
    if t is None or len(t) < n + 2:
        return None
    h, l, c = _np(t, "high"), _np(t, "low"), _np(t, "close")
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * atr, hl2 - mult * atr
    fub, flb = ub.copy(), lb.copy()
    d = np.ones(len(c))
    for i in range(1, len(c)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if c[i] > fub[i - 1]:
            d[i] = 1
        elif c[i] < flb[i - 1]:
            d[i] = -1
        else:
            d[i] = d[i - 1]
    return float(d[-1]), float(d[-2])


def _heikin(t, k=60):  # -> (ha_open_now, ha_close_now, ha_open_prev, ha_close_prev)
    if t is None or len(t) < 3:
        return None
    w = t.iloc[-k:]
    o, h, l, c = _np(w, "open"), _np(w, "high"), _np(w, "low"), _np(w, "close")
    ha_c = (o + h + l + c) / 4
    ha_o = np.empty(len(o))
    ha_o[0] = (o[0] + c[0]) / 2
    for i in range(1, len(o)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    return float(ha_o[-1]), float(ha_c[-1]), float(ha_o[-2]), float(ha_c[-2])


def _obv(t, ema_p):  # -> (obv_now - ema_now)
    if t is None or len(t) < ema_p + 1:
        return None
    sign = np.sign(t["close"].diff().fillna(0.0))
    obv = (sign * t["volume"]).cumsum()
    return float(obv.iloc[-1] - obv.ewm(span=ema_p, adjust=False).mean().iloc[-1])


def _force_index(t, n):  # EMA of (close.diff * volume); return (now, prev)
    if t is None or len(t) < n + 2:
        return None
    fi = (t["close"].diff() * t["volume"]).ewm(span=n, adjust=False).mean()
    return float(fi.iloc[-1]), float(fi.iloc[-2])


def _trix(t, n):  # -> (now, prev) in pct
    if t is None or len(t) < n * 3 + 1:
        return None
    e = _ema_s(_np(t, "close"), n)
    e2 = e.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    tr = e3.pct_change() * 100
    return float(tr.iloc[-1]), float(tr.iloc[-2])


def _awesome(t):  # -> (now, prev)
    if t is None or len(t) < 35:
        return None
    med = (t["high"] + t["low"]) / 2
    ao = med.rolling(5).mean() - med.rolling(34).mean()
    return float(ao.iloc[-1]), float(ao.iloc[-2])


def _ultimate(t):  # classic 7/14/28 -> 0..100
    if t is None or len(t) < 29:
        return None
    c = t["close"]
    prev_c = c.shift()
    bp = c - pd.concat([t["low"], prev_c], axis=1).min(axis=1)
    tr = pd.concat([t["high"], prev_c], axis=1).max(axis=1) - pd.concat([t["low"], prev_c], axis=1).min(axis=1)
    tr = tr.replace(0, np.nan)

    def avg(p):
        return bp.iloc[-p:].sum() / tr.iloc[-p:].sum()

    a7, a14, a28 = avg(7), avg(14), avg(28)
    if np.isnan([a7, a14, a28]).any():
        return None
    return float(100 * (4 * a7 + 2 * a14 + a28) / 7)


def _fisher(t, n):  # -> (now, prev)
    if t is None or len(t) < n + 2:
        return None
    med = (t["high"] + t["low"]) / 2
    w = med.iloc[-(n + 2):]
    lo = w.rolling(n).min()
    hi = w.rolling(n).max()
    rng = (hi - lo).replace(0, np.nan)
    val = (2 * ((med.iloc[-(n + 2):] - lo) / rng) - 1).clip(-0.999, 0.999)
    fish = np.zeros(len(val))
    v = 0.0
    f = 0.0
    out = []
    for x in val.to_numpy():
        if np.isnan(x):
            out.append(np.nan)
            continue
        v = 0.33 * 2 * x + 0.67 * v
        v = min(max(v, -0.999), 0.999)
        f = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * f
        out.append(f)
    if len(out) < 2 or np.isnan(out[-1]) or np.isnan(out[-2]):
        return None
    return float(out[-1]), float(out[-2])


def _coppock(t):  # WMA(10) of (ROC14 + ROC11) -> (now, prev)
    if t is None or len(t) < 30:
        return None
    c = t["close"]
    roc = (c.pct_change(14) * 100 + c.pct_change(11) * 100).to_numpy()

    def cop_at(end):
        seg = roc[end - 9:end + 1]
        return None if np.isnan(seg).any() else _wma_at(roc, 10, end)

    now, prev = cop_at(len(roc) - 1), cop_at(len(roc) - 2)
    return None if None in (now, prev) else (now, prev)


def _elder(t, n=13):  # -> (bull_power, bear_power)
    if t is None or len(t) < n + 1:
        return None
    e = _ema_s(_np(t, "close"), n).iloc[-1]
    return float(t["high"].iloc[-1] - e), float(t["low"].iloc[-1] - e)


# ------------------------ strategy factories -----------------------------
# Each returns (enter, exit); both (ctx, symbol) -> bool. Long-flat.
def ma_cross_gen(fn, fast, slow, win):
    def vals(ctx, s):
        t = _t(ctx, s, win)
        if t is None:
            return None
        x = _np(t, "close")
        f, sl = fn(x, fast), fn(x, slow)
        pf, ps = fn(x[:-1], fast), fn(x[:-1], slow)
        if None in (f, sl, pf, ps):
            return None
        return pf, ps, f, sl

    def en(ctx, s):
        v = vals(ctx, s)
        return v is not None and v[0] <= v[1] and v[2] > v[3]

    def ex(ctx, s):
        v = vals(ctx, s)
        return v is not None and v[0] >= v[1] and v[2] < v[3]
    return en, ex


def price_vs_gen(fn, n, win):  # trend: hold while price > adaptive MA
    def en(ctx, s):
        t = _t(ctx, s, win)
        if t is None:
            return False
        m = fn(_np(t, "close"), n)
        return m is not None and float(t["close"].iloc[-1]) > m

    def ex(ctx, s):
        t = _t(ctx, s, win)
        if t is None:
            return False
        m = fn(_np(t, "close"), n)
        return m is not None and float(t["close"].iloc[-1]) < m
    return en, ex


def osc_mr_gen(fn, n, lo, hi, win):  # oscillator mean-reversion
    def en(ctx, s):
        v = fn(_t(ctx, s, win), n)
        return v is not None and v < lo

    def ex(ctx, s):
        v = fn(_t(ctx, s, win), n)
        return v is not None and v > hi
    return en, ex


def osc_level_gen(fn, n, lvl, win):  # cross a level upward = trend long
    def vals(ctx, s):
        t = _t(ctx, s, win)
        if t is None:
            return None
        cur = fn(t, n)
        prev = fn(t.iloc[:-1], n)
        return None if None in (cur, prev) else (prev, cur)

    def en(ctx, s):
        v = vals(ctx, s)
        return v is not None and v[0] <= lvl and v[1] > lvl

    def ex(ctx, s):
        v = vals(ctx, s)
        return v is not None and v[0] >= lvl and v[1] < lvl
    return en, ex


# 50 specs: (name, family, (enter, exit))
SPECS = [
    # --- adaptive moving-average zoo (7) ---
    ("DEMA cross 9/21",   "ma-adaptive", ma_cross_gen(_dema_last, 9, 21, 160)),
    ("TEMA cross 9/21",   "ma-adaptive", ma_cross_gen(_tema_last, 9, 21, 160)),
    ("HMA cross 9/21",    "ma-adaptive", ma_cross_gen(_hma_last, 9, 21, 120)),
    ("HMA cross 16/49",   "ma-adaptive", ma_cross_gen(_hma_last, 16, 49, 260)),
    ("WMA cross 10/30",   "ma-adaptive", ma_cross_gen(_wma_last, 10, 30, 120)),
    ("KAMA trend 10",     "ma-adaptive", price_vs_gen(_kama_last, 10, 160)),
    # --- Williams %R (3) ---
    ("Williams%R 14 MR",  "williams",    osc_mr_gen(_williams_r, 14, -80, -20, 40)),
    ("Williams%R 28 MR",  "williams",    osc_mr_gen(_williams_r, 28, -80, -20, 60)),
    ("Williams%R 14 trend", "williams",  osc_level_gen(_williams_r, 14, -50, 40)),
    # --- CCI (3) ---
    ("CCI 20 MR",         "cci",         osc_mr_gen(_cci, 20, -100, 100, 60)),
    ("CCI 50 MR",         "cci",         osc_mr_gen(_cci, 50, -100, 100, 120)),
    ("CCI 20 zero trend", "cci",         osc_level_gen(_cci, 20, 0, 60)),
    # --- Chande Momentum Osc (2) ---
    ("CMO 14 MR",         "cmo",         osc_mr_gen(_cmo, 14, -50, 50, 60)),
    ("CMO 9 zero trend",  "cmo",         osc_level_gen(_cmo, 9, 0, 40)),
    # --- Money Flow Index (2) ---
    ("MFI 14 20/80",      "mfi",         osc_mr_gen(_mfi, 14, 20, 80, 60)),
    ("MFI 28 20/80",      "mfi",         osc_mr_gen(_mfi, 28, 20, 80, 90)),
    # --- StochRSI (2) ---
    ("StochRSI 14 .2/.8", "stochrsi",    osc_mr_gen(_stochrsi, 14, 0.2, 0.8, 90)),
    ("StochRSI 14 .1/.9", "stochrsi",    osc_mr_gen(_stochrsi, 14, 0.1, 0.9, 90)),
    # --- z-score mean-reversion (3) ---
    ("Z-score 20 +/-2",   "zscore",      osc_mr_gen(_zscore, 20, -2.0, 2.0, 40)),
    ("Z-score 50 +/-2",   "zscore",      osc_mr_gen(_zscore, 50, -2.0, 2.0, 80)),
    ("Z-score 20 +/-1.5", "zscore",      osc_mr_gen(_zscore, 20, -1.5, 1.5, 40)),
    # --- Bollinger %B (2) ---
    ("%B 20 MR .05/.5",   "percent-b",   osc_mr_gen(_percent_b, 20, 0.05, 0.5, 40)),
    ("%B 20 trend .8",    "percent-b",   osc_level_gen(_percent_b, 20, 0.8, 40)),
    # --- DPO (1) ---
    ("DPO 20 MR",         "dpo",         osc_mr_gen(_dpo, 20, 0.0, 0.0, 60)),  # enter price<detrend, exit above
    # --- ADX / DMI (3) ---
    ("DI cross ADX>20",   "adx",         None),
    ("DI cross ADX>25",   "adx",         None),
    ("ADX>25 EMA9/21",    "adx",         None),
    # --- Vortex (2) ---
    ("Vortex 14 cross",   "vortex",      None),
    ("Vortex 21 cross",   "vortex",      None),
    # --- Aroon (2) ---
    ("Aroon 25 cross",    "aroon",       None),
    ("Aroon up>70",       "aroon",       None),
    # --- Supertrend (3) ---
    ("Supertrend 10/3",   "supertrend",  None),
    ("Supertrend 7/2",    "supertrend",  None),
    ("Supertrend 20/4",   "supertrend",  None),
    # --- Heikin-Ashi (2) ---
    ("Heikin-Ashi flip",  "heikin",      None),
    ("HA flip + EMA50",   "heikin",      None),
    # --- volume / OBV / Force (3) ---
    ("OBV vs EMA20",      "volume",      None),
    ("Force-index 13 cross", "volume",   None),
    ("Vol-spike reversal", "volume",     None),
    # --- TRIX (2) ---
    ("TRIX 15 zero",      "trix",        None),
    ("TRIX 9 zero",       "trix",        None),
    # --- Awesome Osc (2) ---
    ("Awesome zero cross", "awesome",    None),
    ("Awesome saucer",    "awesome",     None),
    # --- Ultimate Osc (1) ---
    ("Ultimate 30/70",    "ultimate",    osc_mr_gen(lambda t, n: _ultimate(t), 0, 30, 70, 40)),
    # --- Fisher transform (1) ---
    ("Fisher zero cross", "fisher",      None),
    # --- Coppock (1) ---
    ("Coppock sign",      "coppock",     None),
    # --- Elder-Ray (1) ---
    ("Elder-Ray 13",      "elder",       None),
    # --- price-action / volatility (3) ---
    ("3-down fade",       "price-action", None),
    ("3-up momentum",     "price-action", None),
    ("Vol-breakout ATR1", "volatility",  None),
]


# ---- factories for the multi-output / stateful specs (filled in below) ----
def _make_special(name):
    if name == "DI cross ADX>20":
        def en(ctx, s):
            r = _adx(_t(ctx, s, 90), 14)
            return r is not None and r[0] > r[1] and r[2] > 20

        def ex(ctx, s):
            r = _adx(_t(ctx, s, 90), 14)
            return r is not None and r[0] < r[1]
        return en, ex
    if name == "DI cross ADX>25":
        def en(ctx, s):
            r = _adx(_t(ctx, s, 90), 14)
            return r is not None and r[0] > r[1] and r[2] > 25

        def ex(ctx, s):
            r = _adx(_t(ctx, s, 90), 14)
            return r is not None and r[0] < r[1]
        return en, ex
    if name == "ADX>25 EMA9/21":
        def en(ctx, s):
            t = _t(ctx, s, 90)
            r = _adx(t, 14)
            if r is None or r[2] <= 25:
                return False
            x = _np(t, "close")
            return float(_ema_s(x, 9).iloc[-1]) > float(_ema_s(x, 21).iloc[-1])

        def ex(ctx, s):
            t = _t(ctx, s, 90)
            if t is None:
                return False
            x = _np(t, "close")
            return float(_ema_s(x, 9).iloc[-1]) < float(_ema_s(x, 21).iloc[-1])
        return en, ex
    if name in ("Vortex 14 cross", "Vortex 21 cross"):
        n = 14 if "14" in name else 21
        win = n * 4

        def vals(ctx, s):
            t = _t(ctx, s, win)
            if t is None:
                return None
            cur = _vortex(t, n)
            prev = _vortex(t.iloc[:-1], n)
            return None if None in (cur, prev) else (cur, prev)

        def en(ctx, s):
            v = vals(ctx, s)
            return v is not None and v[1][0] <= v[1][1] and v[0][0] > v[0][1]

        def ex(ctx, s):
            v = vals(ctx, s)
            return v is not None and v[1][0] >= v[1][1] and v[0][0] < v[0][1]
        return en, ex
    if name == "Aroon 25 cross":
        def vals(ctx, s):
            t = _t(ctx, s, 60)
            if t is None:
                return None
            cur = _aroon(t, 25)
            prev = _aroon(t.iloc[:-1], 25)
            return None if None in (cur, prev) else (cur, prev)

        def en(ctx, s):
            v = vals(ctx, s)
            return v is not None and v[1][0] <= v[1][1] and v[0][0] > v[0][1]

        def ex(ctx, s):
            v = vals(ctx, s)
            return v is not None and v[1][0] >= v[1][1] and v[0][0] < v[0][1]
        return en, ex
    if name == "Aroon up>70":
        def en(ctx, s):
            a = _aroon(_t(ctx, s, 60), 25)
            return a is not None and a[0] > 70 and a[1] < 30

        def ex(ctx, s):
            a = _aroon(_t(ctx, s, 60), 25)
            return a is not None and a[1] > 70
        return en, ex
    if name.startswith("Supertrend"):
        parts = name.split()[1].split("/")
        n, mult = int(parts[0]), float(parts[1])
        win = n * 6 + 20

        def en(ctx, s):
            r = _supertrend_dir(_t(ctx, s, win), n, mult)
            return r is not None and r[0] > 0 and r[1] < 0

        def ex(ctx, s):
            r = _supertrend_dir(_t(ctx, s, win), n, mult)
            return r is not None and r[0] < 0 and r[1] > 0
        return en, ex
    if name == "Heikin-Ashi flip":
        def en(ctx, s):
            r = _heikin(_t(ctx, s, 80))
            return r is not None and r[1] > r[0] and r[3] <= r[2]

        def ex(ctx, s):
            r = _heikin(_t(ctx, s, 80))
            return r is not None and r[1] < r[0] and r[3] >= r[2]
        return en, ex
    if name == "HA flip + EMA50":
        def en(ctx, s):
            t = _t(ctx, s, 80)
            r = _heikin(t)
            if r is None or not (r[1] > r[0] and r[3] <= r[2]):
                return False
            return float(t["close"].iloc[-1]) > float(_ema_s(_np(t, "close"), 50).iloc[-1])

        def ex(ctx, s):
            r = _heikin(_t(ctx, s, 80))
            return r is not None and r[1] < r[0]
        return en, ex
    if name == "OBV vs EMA20":
        def en(ctx, s):
            v = _obv(_t(ctx, s, 200), 20)
            return v is not None and v > 0

        def ex(ctx, s):
            v = _obv(_t(ctx, s, 200), 20)
            return v is not None and v < 0
        return en, ex
    if name == "Force-index 13 cross":
        def en(ctx, s):
            r = _force_index(_t(ctx, s, 60), 13)
            return r is not None and r[1] <= 0 and r[0] > 0

        def ex(ctx, s):
            r = _force_index(_t(ctx, s, 60), 13)
            return r is not None and r[1] >= 0 and r[0] < 0
        return en, ex
    if name == "Vol-spike reversal":
        def en(ctx, s):  # heavy volume + down bar -> fade
            t = _t(ctx, s, 40)
            if t is None:
                return False
            vol = t["volume"]
            if vol.iloc[-1] < 2.0 * vol.iloc[-20:].mean():
                return False
            return float(t["close"].iloc[-1]) < float(t["open"].iloc[-1])

        def ex(ctx, s):  # exit when a green bar closes above prior high
            t = _t(ctx, s, 5)
            if t is None:
                return False
            return float(t["close"].iloc[-1]) > float(t["high"].iloc[-2])
        return en, ex
    if name.startswith("TRIX"):
        n = 15 if "15" in name else 9
        win = n * 4 + 5

        def en(ctx, s):
            r = _trix(_t(ctx, s, win), n)
            return r is not None and r[1] <= 0 and r[0] > 0

        def ex(ctx, s):
            r = _trix(_t(ctx, s, win), n)
            return r is not None and r[1] >= 0 and r[0] < 0
        return en, ex
    if name == "Awesome zero cross":
        def en(ctx, s):
            r = _awesome(_t(ctx, s, 60))
            return r is not None and r[1] <= 0 and r[0] > 0

        def ex(ctx, s):
            r = _awesome(_t(ctx, s, 60))
            return r is not None and r[1] >= 0 and r[0] < 0
        return en, ex
    if name == "Awesome saucer":
        def en(ctx, s):  # momentum turning up while still positive
            t = _t(ctx, s, 60)
            if t is None:
                return False
            med = (t["high"] + t["low"]) / 2
            ao = (med.rolling(5).mean() - med.rolling(34).mean())
            if ao.iloc[-1] <= 0 or len(ao) < 3:
                return False
            return ao.iloc[-1] > ao.iloc[-2] and ao.iloc[-2] < ao.iloc[-3]

        def ex(ctx, s):
            r = _awesome(_t(ctx, s, 60))
            return r is not None and r[0] < 0
        return en, ex
    if name == "Fisher zero cross":
        def en(ctx, s):
            r = _fisher(_t(ctx, s, 30), 10)
            return r is not None and r[1] <= 0 and r[0] > 0

        def ex(ctx, s):
            r = _fisher(_t(ctx, s, 30), 10)
            return r is not None and r[1] >= 0 and r[0] < 0
        return en, ex
    if name == "Coppock sign":
        def en(ctx, s):
            r = _coppock(_t(ctx, s, 50))
            return r is not None and r[1] <= 0 and r[0] > 0

        def ex(ctx, s):
            r = _coppock(_t(ctx, s, 50))
            return r is not None and r[1] >= 0 and r[0] < 0
        return en, ex
    if name == "Elder-Ray 13":
        def en(ctx, s):  # bear power < 0 rising back (dip in uptrend)
            t = _t(ctx, s, 40)
            r = _elder(t, 13)
            if r is None:
                return False
            x = _np(t, "close")
            up = float(_ema_s(x, 13).iloc[-1]) > float(_ema_s(x, 13).iloc[-2])
            return up and r[1] < 0

        def ex(ctx, s):
            r = _elder(_t(ctx, s, 40), 13)
            return r is not None and r[0] < 0  # bull power negative
        return en, ex
    if name == "3-down fade":
        def en(ctx, s):
            t = _t(ctx, s, 5)
            if t is None or len(t) < 4:
                return False
            c = _np(t, "close")
            return c[-1] < c[-2] < c[-3] < c[-4]

        def ex(ctx, s):
            t = _t(ctx, s, 3)
            if t is None or len(t) < 2:
                return False
            c = _np(t, "close")
            return c[-1] > c[-2]
        return en, ex
    if name == "3-up momentum":
        def en(ctx, s):
            t = _t(ctx, s, 5)
            if t is None or len(t) < 4:
                return False
            c = _np(t, "close")
            return c[-1] > c[-2] > c[-3] > c[-4]

        def ex(ctx, s):
            t = _t(ctx, s, 3)
            if t is None or len(t) < 2:
                return False
            c = _np(t, "close")
            return c[-1] < c[-2]
        return en, ex
    if name == "Vol-breakout ATR1":
        def en(ctx, s):
            t = _t(ctx, s, 30)
            if t is None or len(t) < 16:
                return False
            a = float(ctx.atr(s, 14) or 0)
            if a <= 0:
                return False
            c = _np(t, "close")
            return c[-1] > c[-2] + a

        def ex(ctx, s):
            t = _t(ctx, s, 30)
            if t is None or len(t) < 16:
                return False
            a = float(ctx.atr(s, 14) or 0)
            c = _np(t, "close")
            return a > 0 and c[-1] < c[-2] - a
        return en, ex
    raise KeyError(name)


# bind the special factories
SPECS = [
    (name, fam, fns if fns is not None else _make_special(name))
    for (name, fam, fns) in SPECS
]
assert len(SPECS) == 50, f"expected 50 specs, got {len(SPECS)}"


class _P(BaseModel):
    model_config = {"extra": "allow"}


class FuncStrat(Strategy[_P]):
    PARAMS_MODEL = _P

    def on_init(self) -> None:
        self.symbol = self.symbols[0]

    def on_bar(self, ctx) -> None:
        s = self.symbol
        try:
            pos = float(ctx.position(s))
            if pos == 0:
                if self._enter(ctx, s):
                    _enter_full(ctx, s)
            else:
                if self._exit(ctx, s):
                    _exit_full(ctx, s)
        except Exception:  # noqa: BLE001 -- one bad bar shouldn't kill the cell
            return


async def main() -> None:
    bases = os.environ.get("MATRIX_SYMBOLS")
    bases = bases.split(",") if bases else DEFAULT_SYMBOLS
    symbols = [f"{b}{QUOTE}" for b in bases]
    max_cells = int(os.environ.get("MATRIX_MAX_CELLS", "0")) or None

    engine = get_engine()
    out = open(OUT_PATH, "w")
    cells = 0
    t_all = time.time()
    for tf, start in TIMEFRAMES:
        for symbol in symbols:
            t0 = time.time()
            df = await load_bars(engine, symbol, tf, start=start, end=WIN_END)
            meta = await load_instrument_meta(engine, [symbol])
            n = 0 if df is None else len(df)
            print(f"[load] {tf} {symbol}: {n} bars in {time.time()-t0:.1f}s",
                  file=sys.stderr, flush=True)
            for name, family, (en, ex) in SPECS:
                if max_cells and cells >= max_cells:
                    break
                rec = {"tf": tf, "symbol": symbol, "strategy": name, "family": family}
                t0 = time.time()
                try:
                    if df is None or df.empty:
                        rec["error"] = "no bars"
                    else:
                        strat = FuncStrat(symbols=[symbol], params=_P())
                        strat._enter, strat._exit = en, ex
                        cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                             fee_rate_bps=10, slippage_bps=5,
                                             instrument_meta=meta)
                        result = run_backtest(strat, {symbol: df}, cfg)
                        a = compute_analytics(result)
                        rec["bars"] = n
                        rec["stats"] = {
                            "total_return_pct": a.total_return_pct,
                            "sharpe": a.sharpe_ratio,
                            "max_drawdown_pct": a.max_drawdown_pct,
                            "num_trades": a.num_closed_trades,
                            "win_rate_pct": a.win_rate_pct,
                            "profit_factor": a.profit_factor,
                        }
                except Exception as e:  # noqa: BLE001
                    rec["error"] = f"{type(e).__name__}: {e}"
                rec["secs"] = round(time.time() - t0, 1)
                out.write(json.dumps(rec, default=float) + "\n")
                out.flush()
                cells += 1
                r = rec.get("stats", {}).get("total_return_pct")
                tag = "ERR " + rec["error"] if "error" in rec else f"{r:+.1f}%"
                print(f"[{cells}] {tf} {symbol.split('-')[0]} | {name}: {tag} ({rec['secs']}s)",
                      file=sys.stderr, flush=True)
            if max_cells and cells >= max_cells:
                break
        if max_cells and cells >= max_cells:
            break
    out.close()
    await engine.dispose()
    print(f"[done] {cells} cells in {time.time()-t_all:.1f}s -> {OUT_PATH}",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
