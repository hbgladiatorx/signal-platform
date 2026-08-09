"""Cross-sectional short-term reversal on 15m crypto, taker vs maker/limit fills.

DIFFERENT ALPHA SOURCE (not TA-on-close): each bar, rank the universe by trailing
k-bar return and long the biggest losers (short-horizon reversal). Tested under two
cost models over the full 2024-01-01..2026-06-22 window:

  taker  : market in/out at next open, slip applied, fee each side  (the cost wall)
  maker  : resting limit at close*(1-offset); FILLS ONLY IF next bar trades to it
           (buy fills iff low<=limit, sell iff high>=limit), maker fee, no slippage.
           If a limit does NOT fill, we fall back to a taker fill next bar — no free
           lunch. Reports fill-rate + turnover so the maker benefit is auditable.

Modes: long-only (spot/live-deployable) and long-short (dollar-neutral DIAGNOSTIC
of whether the reversal alpha exists at all; not live on spot).

  docker compose run --rm -w /app -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/vec_xreversal.py:/tmp/v.py \
    -v /home/signal/app/logs:/app/logs backtest_worker python /tmp/v.py
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone

import numpy as np

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars

TF = "15m"
BARS_PER_YEAR = 365 * 24 * 4
FEE_BPS = 10.0
TAKER_SLIP_BPS = 5.0
UNIVERSE = ["BTC", "ETH", "SOL", "XRP", "XLM", "BNB", "ADA", "AVAX", "NEAR", "DOGE",
            "SUI", "LTC", "LINK", "FET", "HBAR", "DOT", "ALGO", "BCH", "ATOM", "SHIB",
            "ICP", "UNI", "FIL", "OP", "ARB", "ETC", "AAVE", "APT"]
S0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
S1 = datetime(2026, 6, 22, tzinfo=timezone.utc)


def simulate(O, H, L, C, retk, n_long, h, maker, offset_bps, long_short, momentum=False):
    """Time-loop portfolio sim. O/H/L/C/retk are [T,S] aligned arrays.

    Returns metrics dict. Costs: fee each side; taker adds slip; maker fills only
    when price touches the limit (else taker fallback next bar)."""
    T, S = C.shape
    fee = FEE_BPS / 1e4
    slip = TAKER_SLIP_BPS / 1e4
    off = offset_bps / 1e4
    cash = 10000.0
    qty = np.zeros(S)
    equity = np.empty(T)
    turn_notional = 0.0
    maker_fills = 0
    taker_fills = 0
    for t in range(T):
        px = np.nan_to_num(C[t], nan=0.0)
        eq = cash + float(qty @ px)
        equity[t] = eq
        if t % h != 0 or t + 1 >= T or eq <= 0:
            continue
        r = retk[t]
        valid = ~np.isnan(r)
        nv = int(valid.sum())
        if nv < 2 * n_long + 2:
            continue
        order = np.argsort(np.where(valid, r, np.inf))   # ascending: losers first
        losers = order[:n_long]
        winners = order[nv - n_long:nv]
        long_leg = winners if momentum else losers        # momentum longs winners
        short_leg = losers if momentum else winners
        w = np.zeros(S)
        w[long_leg] = 1.0 / n_long
        if long_short:
            w[short_leg] = -1.0 / n_long
            w *= 0.5                                       # gross 1.0 (0.5 long / 0.5 short)
        # current weights, target trade in notional at t+1
        nxt = t + 1
        cur_notional = qty * np.nan_to_num(C[t], nan=0.0)
        tgt_notional = w * eq
        d_not = tgt_notional - cur_notional               # +buy / -sell per symbol
        for s in range(S):
            dn = d_not[s]
            if abs(dn) < eq * 1e-4 or np.isnan(C[nxt, s]) or np.isnan(C[t, s]):
                continue
            if dn > 0:                                     # BUY
                limit = C[t, s] * (1 - off)
                if maker and L[nxt, s] <= limit:
                    fill = limit; f = fee; maker_fills += 1
                else:
                    fill = O[nxt, s] * (1 + slip); f = fee + (0 if maker else 0); taker_fills += 1
                    if maker:  # taker fallback still pays slip
                        fill = O[nxt, s] * (1 + slip)
                add_qty = dn / fill
                qty[s] += add_qty
                cash -= add_qty * fill * (1 + f)
                turn_notional += abs(dn)
            else:                                          # SELL
                limit = C[t, s] * (1 + off)
                if maker and H[nxt, s] >= limit:
                    fill = limit; f = fee; maker_fills += 1
                else:
                    fill = O[nxt, s] * (1 - slip); f = fee; taker_fills += 1
                    if maker:
                        fill = O[nxt, s] * (1 - slip)
                red_qty = (-dn) / fill
                red_qty = min(red_qty, qty[s]) if qty[s] > 0 else red_qty
                qty[s] -= red_qty
                cash += red_qty * fill * (1 - f)
                turn_notional += abs(dn)
    final = equity[-1]
    ret = (final / 10000.0 - 1) * 100
    peak = np.maximum.accumulate(equity)
    maxdd = np.nanmin((equity - peak) / np.where(peak > 0, peak, np.nan)) * 100
    er = np.diff(equity) / np.where(equity[:-1] > 0, equity[:-1], np.nan)
    sd = np.nanstd(er)
    sharpe = (np.nanmean(er) / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    nfills = maker_fills + taker_fills
    return dict(ret=ret, maxdd=maxdd, sharpe=sharpe, fills=nfills,
                maker_rate=(100 * maker_fills / nfills if nfills else 0.0),
                turn=turn_notional / 10000.0)


async def main():
    engine = get_engine()
    # load + align on common timestamp index
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
    O = np.column_stack([frames[s].reindex(idx)["open"].to_numpy(float) for s in syms])
    H = np.column_stack([frames[s].reindex(idx)["high"].to_numpy(float) for s in syms])
    L = np.column_stack([frames[s].reindex(idx)["low"].to_numpy(float) for s in syms])
    C = np.column_stack([frames[s].reindex(idx)["close"].to_numpy(float) for s in syms])
    T, Sn = C.shape
    days = T / (24 * 4)
    print(f"loaded {Sn} symbols x {T} bars ({days/365.25:.2f}y aligned)\n", flush=True)

    out = open("/app/logs/vec_xreversal.jsonl", "w")
    # ROBUSTNESS: the promising reversal configs, FULL vs 2024(H1) vs 2025-26(H2).
    # A real edge holds in both halves; a mirage shows +big full but flips in a half.
    mid = T // 2
    def slabs():
        return [("full", 0, T), ("H1", 0, mid), ("H2", mid, T)]
    print(f"{'sign':5}{'mode':5}{'k':>4}{'N':>3}{'h':>4}   "
          f"{'FULL ret%':>10}{'H1 ret%':>10}{'H2 ret%':>10}   "
          f"{'shrp_full':>9}{'maxDD':>8}{'mkr%':>6}", flush=True)
    SHORTLIST = [  # (k, N, h, long_short) for reversal
        (48, 5, 16, False), (96, 5, 16, False), (96, 5, 16, True),
        (96, 8, 16, True),  (48, 5, 16, True),  (96, 8, 16, False),
        (48, 5, 8, False),  (96, 5, 8, False),  (48, 5, 8, True),
    ]
    for (k, n_long, h, ls) in SHORTLIST:
        res = {}
        for tag, a, b in slabs():
            retk = np.full((b - a, Sn), np.nan)
            cc = C[a:b]
            retk[k:] = cc[k:] / cc[:-k] - 1.0
            m = simulate(O[a:b], H[a:b], L[a:b], C[a:b], retk, n_long, h, True, 5.0,
                         ls, False)
            res[tag] = m
        mode = "L/S" if ls else "long"
        f, h1, h2 = res["full"], res["H1"], res["H2"]
        print(f"{'rev':5}{mode:5}{k:>4}{n_long:>3}{h:>4}   "
              f"{f['ret']:>+9.1f}%{h1['ret']:>+9.1f}%{h2['ret']:>+9.1f}%   "
              f"{f['sharpe']:>9.1f}{f['maxdd']:>+7.1f}%{f['maker_rate']:>5.0f}%", flush=True)
        out.write(json.dumps(dict(k=k, n=n_long, h=h, mode=mode,
                                  full=f, h1=h1, h2=h2), default=float) + "\n")
        out.flush()
    out.close()
    print("\n-> logs/vec_xreversal.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
