"""Diagnose WHY xsectional 15m reversal dies in H1 2024 but prints in H2 2025-26.

The reversal bet is: rank coins by trailing k-bar return, long losers. It pays iff
trailing relative return is NEGATIVELY related to forward relative return (reversion);
it bleeds if POSITIVELY related (momentum/persistence).

Measure, per half, the cross-sectional Spearman rank corr between trailing k-bar
return and forward h-bar return, averaged over rebalance bars:
  corr > 0  => momentum regime (winners keep winning) => reversal LOSES
  corr < 0  => reversion regime (losers bounce)        => reversal WINS

Also report the long-short decile spread: mean forward h-bar return of the bottom-N
(losers, what we buy) minus the top-N (winners, what we short), in bps per holding
period. Positive spread = reversal makes gross money.

  docker compose run --rm -w /app -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/vec_xreversal_autocorr.py:/tmp/v.py \
    -v /home/signal/app/logs:/app/logs backtest_worker python /tmp/v.py
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import numpy as np

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars

TF = "15m"
# Lighter 12-name liquid universe to dodge DB-load contention; enough for a
# cross-sectional rank-corr read on the 2024 vs 2025-26 regime.
UNIVERSE = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX",
            "LINK", "LTC", "DOT", "BCH"]
S0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
S1 = datetime(2026, 6, 22, tzinfo=timezone.utc)


def rankdata(a):
    """Average-rank a 1D array ignoring NaNs; returns ranks (NaN stays NaN)."""
    out = np.full(a.shape, np.nan)
    valid = ~np.isnan(a)
    v = a[valid]
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(len(v))
    ranks[order] = np.arange(len(v))
    # average ties
    sv = v[order]
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    out[valid] = ranks
    return out


def spearman_row(x, y):
    """Cross-sectional Spearman corr between two same-length rows (NaN-safe)."""
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < 4:
        return np.nan
    rx = rankdata(np.where(m, x, np.nan))
    ry = rankdata(np.where(m, y, np.nan))
    rx = rx[m]; ry = ry[m]
    rx -= rx.mean(); ry -= ry.mean()
    d = np.sqrt((rx @ rx) * (ry @ ry))
    return float(rx @ ry / d) if d > 0 else np.nan


def analyze(C, k, h, n_long, a, b):
    cc = C[a:b]
    T = cc.shape[0]
    trail = np.full_like(cc, np.nan)
    trail[k:] = cc[k:] / cc[:-k] - 1.0          # trailing k-bar return at t
    fwd = np.full_like(cc, np.nan)
    fwd[:-h] = cc[h:] / cc[:-h] - 1.0           # forward h-bar return from t
    corrs = []
    spreads = []
    for t in range(k, T - h, h):                # at each rebalance bar
        x = trail[t]; y = fwd[t]
        c = spearman_row(x, y)
        if not np.isnan(c):
            corrs.append(c)
        m = ~np.isnan(x) & ~np.isnan(y)
        if m.sum() >= 2 * n_long + 2:
            order = np.argsort(np.where(m, x, np.inf))
            nv = int(m.sum())
            losers = order[:n_long]             # what reversal BUYS
            winners = order[nv - n_long:nv]     # what reversal SHORTS
            spreads.append(float(np.nanmean(y[losers]) - np.nanmean(y[winners])))
    return (float(np.nanmean(corrs)) if corrs else np.nan,
            float(np.nanmean(spreads)) * 1e4 if spreads else np.nan,  # bps
            len(corrs))


async def main():
    engine = get_engine()
    frames = {}
    for base in UNIVERSE:
        df = await load_bars(engine, f"{base}-USDT@BINANCEUS", TF, start=S0, end=S1)
        if df is not None and not df.empty:
            frames[base] = df
    await engine.dispose()
    import pandas as pd
    idx = None
    for df in frames.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    syms = sorted(frames.keys())
    C = np.column_stack([frames[s].reindex(idx)["close"].to_numpy(float) for s in syms])
    T = C.shape[0]
    mid = T // 2
    print(f"loaded {len(syms)} symbols x {T} bars ({T/(24*4)/365.25:.2f}y)\n", flush=True)
    slabs = [("full", 0, T), ("H1-2024", 0, mid), ("H2-25/26", mid, T)]

    # ROUND-TRIP COST for reference: fee both sides + slip ~= (2*10 + 2*5)/2... use 30 bps
    print("corr<0 = reversion (reversal WINS gross) | corr>0 = momentum (reversal LOSES)")
    print("spread = mean fwd-return(losers we buy) - (winners we short), in bps/hold\n")
    print(f"{'k':>4}{'h':>4}  {'slab':10}  {'spearman':>9}  {'LS spread bps':>14}  {'n_rebal':>8}", flush=True)
    out = open("/app/logs/vec_xreversal_autocorr.jsonl", "w")
    for (k, h) in [(48, 8), (96, 8), (48, 16), (96, 16)]:
        for tag, a, b in slabs:
            corr, spread, n = analyze(C, k, h, 3, a, b)
            print(f"{k:>4}{h:>4}  {tag:10}  {corr:>+9.4f}  {spread:>+14.2f}  {n:>8}", flush=True)
            out.write(json.dumps(dict(k=k, h=h, slab=tag, spearman=corr,
                                      ls_spread_bps=spread, n_rebal=n)) + "\n")
        print(flush=True)
    out.close()
    print("-> logs/vec_xreversal_autocorr.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
