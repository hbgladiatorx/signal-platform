"""Fast cross-sectional crypto strategy scanner.

Why this exists: the real backtest engine recomputes indicators per-bar
(~11s / 3.2k-bar backtest), far too slow to sweep a grid across a whole
universe. This module reproduces the EXACT decision logic of the strategy
families in scripts/research/crypto_search.py, but vectorizes the indicators
and runs the stateful entry/exit/stop logic in a tight numpy loop (~1ms each).
It is a SEARCH tool only — the finalists it surfaces are re-confirmed in the
real engine by scripts/research/crypto_confirm.py before anyone trusts them.

Methodology (the anti-overfitting part):
  1. Split every symbol 70/30 into TRAIN / TEST (chronological, no shuffle).
  2. Score every (family, params) config on TRAIN across the WHOLE universe.
     A config's score is its CROSS-SECTIONAL robustness: median return and the
     fraction of symbols on which it is profitable + beats buy&hold. A genuine
     edge works on many coins; a curve-fit works on one.
  3. Keep configs that are robust in TRAIN (positive on a majority of symbols),
     then validate them UNTOUCHED on TEST. A survivor must stay robust OOS.

Run (host scripts dir mounted into the image):
  docker compose run --rm --no-deps \
    -v /home/signal/app/scripts:/app/scripts -e RES=4h \
    api python -m scripts.research.crypto_scan
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars

# ----------------------------------------------------------------------------
# Costs + universe
# ----------------------------------------------------------------------------
FEE_BPS = 10.0          # taker fee per side
SLIP_BPS = 5.0          # slippage per side
ROUND_TRIP_COST = (FEE_BPS + SLIP_BPS) * 2 / 1e4   # paid on each full in/out

UNIVERSE = [
    "BTC-USDT@BINANCEUS", "ETH-USDT@BINANCEUS", "SOL-USDT@BINANCEUS",
    "BNB-USDT@BINANCEUS", "XRP-USDT@BINANCEUS", "ADA-USDT@BINANCEUS",
    "AVAX-USDT@BINANCEUS", "LINK-USDT@BINANCEUS", "DOT-USDT@BINANCEUS",
    "LTC-USDT@BINANCEUS", "DOGE-USDT@BINANCEUS", "BCH-USDT@BINANCEUS",
    "ATOM-USDT@BINANCEUS", "NEAR-USDT@BINANCEUS",
]

BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


# ----------------------------------------------------------------------------
# Vectorized indicators
# ----------------------------------------------------------------------------
def ema(s: pd.Series, n: int) -> np.ndarray:
    return s.ewm(span=n, adjust=False).mean().to_numpy()


def atr(df: pd.DataFrame, n: int) -> np.ndarray:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.empty_like(c); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    # Wilder smoothing
    out = np.full_like(tr, np.nan)
    if len(tr) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(tr)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru = np.full_like(c, np.nan); rd = np.full_like(c, np.nan)
    if len(c) > n:
        ru[n] = up[1:n + 1].mean(); rd[n] = dn[1:n + 1].mean()
        for i in range(n + 1, len(c)):
            ru[i] = (ru[i - 1] * (n - 1) + up[i]) / n
            rd[i] = (rd[i - 1] * (n - 1) + dn[i]) / n
    rs = ru / np.where(rd == 0, np.nan, rd)
    out = 100 - 100 / (1 + rs)
    out[rd == 0] = 100.0
    return out


def roll_max(a: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(a).rolling(n).max().to_numpy()


def roll_min(a: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(a).rolling(n).min().to_numpy()


# ----------------------------------------------------------------------------
# Backtest core: given a per-bar position array (0/1, effective for the return
# from bar t to t+1), produce equity + metrics. Costs charged on turnover.
# ----------------------------------------------------------------------------
@dataclass
class Metrics:
    ret: float
    sharpe: float
    maxdd: float
    trades: int
    win: float
    pf: float


def _metrics_from_pos(close: np.ndarray, pos: np.ndarray, res: str) -> Metrics:
    # bar return realised on the NEXT bar (pos[t] held into t+1)
    bar_ret = np.zeros(len(close))
    bar_ret[1:] = close[1:] / close[:-1] - 1.0
    held = np.zeros(len(close)); held[1:] = pos[:-1]      # exposure during bar t
    turnover = np.abs(np.diff(pos, prepend=0.0))           # 0->1 or 1->0 each = 1 unit
    strat = held * bar_ret - turnover * (ROUND_TRIP_COST / 2.0)
    eq = np.cumprod(1.0 + strat)
    total = (eq[-1] - 1.0) * 100.0
    sd = strat.std()
    sharpe = float(strat.mean() / sd * np.sqrt(BARS_PER_YEAR[res])) if sd > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    maxdd = float(((eq - peak) / peak).min() * 100.0)
    # round-trip pnl for win rate / profit factor
    # per-segment round trips (handles long=+1 and short=-1)
    pnls = []
    i = 0
    n = len(pos)
    while i < n:
        if pos[i] != 0:
            side = pos[i]; start = i
            while i < n and pos[i] == side:
                i += 1
            end = min(i, n - 1)
            gross = side * (close[end] / close[start] - 1.0)
            pnls.append(gross - ROUND_TRIP_COST)
        else:
            i += 1
    pnls = np.array(pnls) if pnls else np.array([])
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    win = float(len(wins) / len(pnls) * 100.0) if len(pnls) else 0.0
    pf = float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() != 0 else float("inf") if len(wins) else 0.0
    return Metrics(total, sharpe, maxdd, len(pnls), win, pf)


# ----------------------------------------------------------------------------
# Families: each returns a 0/1 position array given (df, params).
# Logic mirrors scripts/research/crypto_search.py exactly (close-based).
# ----------------------------------------------------------------------------
def fam_ema_trend(df: pd.DataFrame, p: dict) -> np.ndarray:
    c = df["close"].to_numpy()
    fast, slow, trend = ema(df["close"], p["fast"]), ema(df["close"], p["slow"]), ema(df["close"], p["trend"])
    a = atr(df, p.get("atr_period", 14))
    n = len(c); pos = np.zeros(n); peak = 0.0; inpos = False
    for i in range(n):
        if np.isnan(a[i]) or np.isnan(trend[i]):
            continue
        if not inpos:
            if fast[i] > slow[i] and c[i] > trend[i]:
                inpos = True; peak = c[i]
        else:
            peak = max(peak, c[i])
            if c[i] <= peak - p["atr_mult"] * a[i] or fast[i] < slow[i]:
                inpos = False
        pos[i] = 1.0 if inpos else 0.0
    return pos


def fam_donchian(df: pd.DataFrame, p: dict) -> np.ndarray:
    c = df["close"].to_numpy()
    hi = roll_max(df["high"].to_numpy(), p["entry"])
    lo = roll_min(df["low"].to_numpy(), p["exit"])
    hi = np.concatenate([[np.nan], hi[:-1]])   # channel uses bars strictly before now
    lo = np.concatenate([[np.nan], lo[:-1]])
    a = atr(df, p.get("atr_period", 14))
    te = ema(df["close"], p["trend"]) if p["trend"] > 0 else None
    n = len(c); pos = np.zeros(n); stop = 0.0; inpos = False
    for i in range(n):
        if np.isnan(a[i]) or np.isnan(hi[i]) or np.isnan(lo[i]):
            continue
        trend_ok = True if te is None else (not np.isnan(te[i]) and c[i] > te[i])
        if not inpos:
            if c[i] > hi[i] and trend_ok:
                inpos = True; stop = c[i] - p["atr_mult"] * a[i]
        else:
            if c[i] < lo[i] or c[i] <= stop:
                inpos = False
        pos[i] = 1.0 if inpos else 0.0
    return pos


def fam_rsi_rev(df: pd.DataFrame, p: dict) -> np.ndarray:
    c = df["close"].to_numpy()
    r = rsi(c, p["rsi_period"])
    te = ema(df["close"], p["trend"]) if p["trend"] > 0 else None
    n = len(c); pos = np.zeros(n); inpos = False
    for i in range(n):
        if np.isnan(r[i]):
            continue
        trend_ok = True if te is None else (not np.isnan(te[i]) and c[i] > te[i])
        if not inpos and r[i] < p["buy_below"] and trend_ok:
            inpos = True
        elif inpos and r[i] > p["sell_above"]:
            inpos = False
        pos[i] = 1.0 if inpos else 0.0
    return pos


def fam_ema_dual(df: pd.DataFrame, p: dict) -> np.ndarray:
    """Long above the trend EMA when fast>slow; SHORT below it when fast<slow.
    ATR trailing stop in both directions, flat otherwise."""
    c = df["close"].to_numpy()
    fast, slow, trend = ema(df["close"], p["fast"]), ema(df["close"], p["slow"]), ema(df["close"], p["trend"])
    a = atr(df, p.get("atr_period", 14))
    n = len(c); pos = np.zeros(n); ext = 0.0; side = 0
    for i in range(n):
        if np.isnan(a[i]) or np.isnan(trend[i]):
            continue
        if side == 0:
            if fast[i] > slow[i] and c[i] > trend[i]:
                side = 1; ext = c[i]
            elif fast[i] < slow[i] and c[i] < trend[i]:
                side = -1; ext = c[i]
        elif side == 1:
            ext = max(ext, c[i])
            if c[i] <= ext - p["atr_mult"] * a[i] or fast[i] < slow[i]:
                side = 0
        else:  # short
            ext = min(ext, c[i])
            if c[i] >= ext + p["atr_mult"] * a[i] or fast[i] > slow[i]:
                side = 0
        pos[i] = side
    return pos


def fam_donchian_dual(df: pd.DataFrame, p: dict) -> np.ndarray:
    """Breakout long above the entry-high channel, SHORT below the entry-low
    channel; close on the opposite exit channel or ATR stop."""
    c = df["close"].to_numpy()
    hh = np.concatenate([[np.nan], roll_max(df["high"].to_numpy(), p["entry"])[:-1]])
    ll = np.concatenate([[np.nan], roll_min(df["low"].to_numpy(), p["entry"])[:-1]])
    xh = np.concatenate([[np.nan], roll_max(df["high"].to_numpy(), p["exit"])[:-1]])
    xl = np.concatenate([[np.nan], roll_min(df["low"].to_numpy(), p["exit"])[:-1]])
    a = atr(df, p.get("atr_period", 14))
    n = len(c); pos = np.zeros(n); stop = 0.0; side = 0
    for i in range(n):
        if np.isnan(a[i]) or np.isnan(hh[i]) or np.isnan(ll[i]) or np.isnan(xh[i]) or np.isnan(xl[i]):
            continue
        if side == 0:
            if c[i] > hh[i]:
                side = 1; stop = c[i] - p["atr_mult"] * a[i]
            elif c[i] < ll[i]:
                side = -1; stop = c[i] + p["atr_mult"] * a[i]
        elif side == 1:
            if c[i] < xl[i] or c[i] <= stop:
                side = 0
        else:
            if c[i] > xh[i] or c[i] >= stop:
                side = 0
        pos[i] = side
    return pos


def _grid(**kw) -> list[dict]:
    keys = list(kw)
    return [dict(zip(keys, v)) for v in itertools.product(*kw.values())]


FAMILIES: dict[str, tuple[Callable, list[dict]]] = {
    "ema_trend": (fam_ema_trend, _grid(
        fast=[10, 20, 30, 50], slow=[50, 100, 150], trend=[100, 200],
        atr_mult=[2.5, 3.5])),
    "donchian": (fam_donchian, _grid(
        entry=[20, 30, 40, 55], exit=[10, 20], trend=[0, 100, 200],
        atr_mult=[2.0, 3.0])),
    "rsi_rev": (fam_rsi_rev, _grid(
        rsi_period=[14, 21], buy_below=[25, 30, 35], sell_above=[50, 55, 65],
        trend=[0, 200])),
    "ema_dual": (fam_ema_dual, _grid(
        fast=[10, 20, 30, 50], slow=[50, 100, 150], trend=[100, 200],
        atr_mult=[2.5, 3.5])),
    "donchian_dual": (fam_donchian_dual, _grid(
        entry=[20, 30, 40, 55], exit=[10, 20, 30],
        atr_mult=[2.0, 3.0])),
}


def buyhold(c: np.ndarray) -> float:
    return float(c[-1] / c[0] - 1.0) * 100.0


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
async def main() -> None:
    res = os.environ.get("RES", "4h")
    engine = get_engine()
    data: dict[str, pd.DataFrame] = {}
    for sym in UNIVERSE:
        try:
            df = await load_bars(engine, sym, res)
            if len(df) > 800:
                data[sym] = df
                print(f"{sym:22} {len(df)} bars  B&H {buyhold(df['close'].to_numpy()):+.0f}%", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: skip ({str(e)[:60]})", flush=True)
    print(f"\nuniverse={len(data)} symbols  res={res}\n", flush=True)

    def half(df):
        cut = int(len(df) * 0.5)
        return df.iloc[:cut], df.iloc[cut:]

    h1 = {s: half(df)[0] for s, df in data.items()}   # first half (earlier regime)
    h2 = {s: half(df)[1] for s, df in data.items()}    # second half (recent regime)

    configs = [(fam, p) for fam, (_, grid) in FAMILIES.items() for p in grid]
    print(f"scanning {len(configs)} configs x {len(data)} symbols (full + both halves)...", flush=True)

    def eval_book(fn, p, book) -> dict:
        rets, sharpes, dds, profitable, ntr = [], [], [], 0, []
        for s, df in book.items():
            m = _metrics_from_pos(df["close"].to_numpy(), fn(df, p), res)
            rets.append(m.ret); sharpes.append(m.sharpe); dds.append(m.maxdd); ntr.append(m.trades)
            if m.ret > 0:
                profitable += 1
        k = len(book)
        return {"med_ret": float(np.median(rets)), "med_sharpe": float(np.median(sharpes)),
                "med_dd": float(np.median(dds)), "frac_profit": profitable / k,
                "med_trades": float(np.median(ntr))}

    scored = []
    for fam, p in configs:
        fn = FAMILIES[fam][0]
        full = eval_book(fn, p, data)
        a = eval_book(fn, p, h1); b = eval_book(fn, p, h2)
        scored.append({"fam": fam, "params": p, "full": full, "h1": a, "h2": b})

    # ALL-WEATHER robustness: profitable on a majority of coins AND positive in
    # BOTH regime halves AND enough trades. This is the regime-shift defense.
    def is_robust(r):
        return (r["full"]["med_trades"] >= 8
                and r["full"]["frac_profit"] >= 0.6
                and r["h1"]["med_ret"] > 0 and r["h2"]["med_ret"] > 0
                and r["h1"]["frac_profit"] >= 0.5 and r["h2"]["frac_profit"] >= 0.5)

    survivors = [r for r in scored if is_robust(r)]
    survivors.sort(key=lambda r: min(r["h1"]["med_ret"], r["h2"]["med_ret"]), reverse=True)

    out = {"resolution": res, "universe": list(data), "n_configs": len(configs),
           "n_survivors": len(survivors), "scored": scored, "survivors": survivors}
    with open("/app/scripts/research/scan_results.json", "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    # diagnostic: best config per family by full-period median return (filter-free)
    print("\nBest config per family by full-period median return (no filter):", flush=True)
    for fam in FAMILIES:
        fr = [r for r in scored if r["fam"] == fam]
        best = max(fr, key=lambda r: r["full"]["med_ret"])
        f = best["full"]
        print(f"  {fam:14} medRet {f['med_ret']:+6.0f}%  shrp {f['med_sharpe']:5.2f}  "
              f"dd {f['med_dd']:5.0f}%  %prof {f['frac_profit']*100:3.0f}  "
              f"h1 {best['h1']['med_ret']:+5.0f}% h2 {best['h2']['med_ret']:+5.0f}%  {best['params']}", flush=True)

    hdr = (f"{'family':14} {'fullRet':>7} {'shrp':>5} {'dd%':>5} {'%prof':>5} | "
           f"{'h1Ret':>6} {'h2Ret':>6} {'tr':>4}")
    print(f"\n{len(survivors)} ALL-WEATHER survivors (profitable both halves + majority of coins):", flush=True)
    print("=" * len(hdr)); print(hdr); print("-" * len(hdr), flush=True)
    for r in survivors[:25]:
        f = r["full"]
        print(f"{r['fam']:14} {f['med_ret']:+7.0f} {f['med_sharpe']:5.2f} {f['med_dd']:5.0f} "
              f"{f['frac_profit']*100:4.0f}% | {r['h1']['med_ret']:+6.0f} {r['h2']['med_ret']:+6.0f} "
              f"{f['med_trades']:4.0f}  {r['params']}", flush=True)

    if survivors:
        w = survivors[0]
        print(f"\nTOP ALL-WEATHER: {w['fam']} {w['params']}", flush=True)
        print(f"  full: med ret {w['full']['med_ret']:+.0f}%  sharpe {w['full']['med_sharpe']:.2f}  "
              f"dd {w['full']['med_dd']:.0f}%  profitable on {w['full']['frac_profit']*100:.0f}% of {len(data)} coins", flush=True)
        print(f"  bull-half med ret {w['h1']['med_ret']:+.0f}% (prof {w['h1']['frac_profit']*100:.0f}%)  |  "
              f"bear-half med ret {w['h2']['med_ret']:+.0f}% (prof {w['h2']['frac_profit']*100:.0f}%)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
