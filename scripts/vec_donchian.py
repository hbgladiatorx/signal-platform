"""Vectorized Donchian-breakout backtester — fast enough for a 2-year 5m sweep.

Exactly mirrors the real engine's fill model so results are comparable:
  - signal computed on bar i using data up to close[i]
  - order fills at NEXT bar's OPEN (i+1) +/- slippage  (engine.py: no same-bar fill)
  - market buy at open*(1+slip_bps), sell at open*(1-slip_bps)
  - fee_bps charged on notional each side; all-in 95% of cash sizing
Donchian: enter long when close[i] > max(high[i-up .. i-1]);
          exit to flat when close[i] < min(low[i-dn .. i-1]).

Validates against the real engine's known 6-month numbers, then runs 2024-01-01..
2026-06-22 across the 8 USDT majors x {20/10,40/20,55/20} x slip {5,15,25,35}.

  docker compose run --rm -d -w /app --name vec_donch \
    -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/vec_donchian.py:/tmp/v.py \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python /tmp/v.py
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone

import numpy as np

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars

TF = "5m"
FEE_BPS = 10.0
BARS_PER_YEAR = 365 * 24 * 12  # 5m bars/yr for annualization
MAJORS = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]
STRATS = {"Donchian 20/10": (20, 10), "Donchian 40/20": (40, 20), "Donchian 55/20": (55, 20)}
SLIPS = [5, 15, 25, 35]


def backtest(o, h, l, c, up, dn, slip_bps, fee_bps=FEE_BPS, alloc=0.95):
    """O(n) vectorized-signal + single state pass. Returns metrics dict."""
    n = len(c)
    # rolling max of high over previous `up` bars (excl current): shift by 1
    roll_hi = _roll_max(h, up)   # max(h[i-up..i-1]) aligned at i
    roll_lo = _roll_min(l, dn)
    enter = c > roll_hi          # boolean signal at bar i (valid where window full)
    exitb = c < roll_lo
    slip = slip_bps / 1e4
    fee = fee_bps / 1e4

    cash = 10000.0
    qty = 0.0
    in_pos = False
    equity = np.empty(n)
    trades = 0
    wins = 0
    gross_win = 0.0
    gross_loss = 0.0
    entry_cost = 0.0
    for i in range(n):
        # execute decision made at bar i-1 using THIS bar's open
        if i > 0:
            op = o[i]
            if not in_pos and enter[i - 1] and not math.isnan(roll_hi[i - 1]):
                fill = op * (1 + slip)
                spend = cash * alloc
                qty = spend / fill
                cash -= spend
                cash -= spend * fee
                entry_cost = spend * (1 + fee)
                in_pos = True
            elif in_pos and exitb[i - 1] and not math.isnan(roll_lo[i - 1]):
                fill = op * (1 - slip)
                proceeds = qty * fill
                cash += proceeds
                cash -= proceeds * fee
                pnl = (proceeds * (1 - fee)) - entry_cost
                trades += 1
                if pnl > 0:
                    wins += 1; gross_win += pnl
                else:
                    gross_loss += -pnl
                qty = 0.0
                in_pos = False
        equity[i] = cash + qty * c[i]
    # close any open position at last close for accounting
    final_eq = cash + qty * c[-1]
    ret = (final_eq / 10000.0 - 1) * 100
    # max drawdown
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    maxdd = dd.min() * 100
    # sharpe from per-bar equity returns, annualized
    er = np.diff(equity) / equity[:-1]
    sd = er.std()
    sharpe = (er.mean() / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (math.inf if gross_win > 0 else 0.0)
    return dict(ret=ret, maxdd=maxdd, sharpe=sharpe, n=trades,
                win=(100 * wins / trades if trades else 0.0),
                pf=(pf if pf != math.inf else 999.0))


def _roll_max(a, w):
    out = np.full(len(a), np.nan)
    if len(a) <= w:
        return out
    # max over [i-w, i-1]
    from numpy.lib.stride_tricks import sliding_window_view
    sw = sliding_window_view(a, w)        # windows ending at index w-1..n-1
    m = sw.max(axis=1)                     # aligned so m[k] = max(a[k..k+w-1])
    out[w:] = m[:-1]                        # value at i uses window [i-w, i-1]
    return out


def _roll_min(a, w):
    out = np.full(len(a), np.nan)
    if len(a) <= w:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    sw = sliding_window_view(a, w)
    m = sw.min(axis=1)
    out[w:] = m[:-1]
    return out


async def load_np(engine, base, start, end):
    df = await load_bars(engine, f"{base}-USDT@BINANCEUS", TF, start=start, end=end)
    if df is None or df.empty:
        return None
    return (df["open"].to_numpy(float), df["high"].to_numpy(float),
            df["low"].to_numpy(float), df["close"].to_numpy(float))


async def main():
    engine = get_engine()

    # --- VALIDATION vs real engine on the 6-month window ---
    v0 = datetime(2025, 12, 15, tzinfo=timezone.utc)
    v1 = datetime(2026, 6, 15, tzinfo=timezone.utc)
    expect = {  # (base, strat, slip) -> real-engine return%
        ("BTC", "Donchian 40/20", 15): 30.9, ("BTC", "Donchian 55/20", 15): 43.8,
        ("ETH", "Donchian 40/20", 15): 87.9, ("BTC", "Donchian 20/10", 15): -13.3,
        ("BTC", "Donchian 20/10", 5): 132.3, ("ETH", "Donchian 20/10", 5): 303.2,
    }
    print("=== VALIDATION (vec vs real engine, 6mo) ===", flush=True)
    for (base, st, slip), real in expect.items():
        o, h, l, c = await load_np(engine, base, v0, v1)
        up, dn = STRATS[st]
        r = backtest(o, h, l, c, up, dn, slip)
        print(f"  {base} {st} @{slip}bp: vec={r['ret']:+.1f}%  real={real:+.1f}%  "
              f"diff={r['ret']-real:+.1f}", flush=True)

    # --- 2-YEAR SWEEP ---
    s0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s1 = datetime(2026, 6, 22, tzinfo=timezone.utc)
    yrs = (s1 - s0).days / 365.25
    out = open("/app/logs/vec_donchian_2yr.jsonl", "w")
    print(f"\n=== 2-YEAR SWEEP {s0.date()}..{s1.date()} ({yrs:.2f}y) ===", flush=True)
    print(f"{'sym':6}{'strat':14}{'slip':>5}{'ret':>10}{'CAGR':>8}{'maxDD':>8}{'shrp':>6}"
          f"{'n':>6}{'/day':>6}{'B&H':>9}", flush=True)
    for base in MAJORS:
        data = await load_np(engine, base, s0, s1)
        if data is None:
            print(f"{base:6} no bars", flush=True); continue
        o, h, l, c = data
        days = len(c) / (24 * 12)
        bh = (c[-1] / c[0] - 1) * 100
        for st, (up, dn) in STRATS.items():
            for slip in SLIPS:
                r = backtest(o, h, l, c, up, dn, slip)
                cagr = ((1 + r["ret"] / 100) ** (1 / yrs) - 1) * 100 if r["ret"] > -100 else -100
                tpd = r["n"] / days
                rec = dict(sym=base, strat=st, slip=slip, bars=len(c),
                           ret=r["ret"], cagr=cagr, maxdd=r["maxdd"], sharpe=r["sharpe"],
                           n=r["n"], tpd=round(tpd, 2), win=r["win"], pf=r["pf"], bh=bh)
                print(f"{base:6}{st.replace('Donchian ',''):14}{slip:>5}{r['ret']:>+9.1f}%"
                      f"{cagr:>+7.1f}%{r['maxdd']:>+7.1f}%{r['sharpe']:>6.1f}{r['n']:>6}"
                      f"{tpd:>6.2f}{bh:>+8.1f}%", flush=True)
                out.write(json.dumps(rec, default=float) + "\n"); out.flush()
    out.close()
    await engine.dispose()
    print("\n-> logs/vec_donchian_2yr.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
