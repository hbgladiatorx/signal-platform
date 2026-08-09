"""Vectorized Ultimate-Oscillator 30/70 mean-reversion backtester — 2-year 15m sweep.

Mirrors the real engine's fill model exactly (same as vec_donchian.py):
  - signal computed on bar i using data up to close[i]
  - order fills at NEXT bar's open (i+1) +/- slippage
  - market buy at open*(1+slip), sell at open*(1-slip); fee_bps on notional each side
  - all-in 95% of cash sizing; long-flat only
Signal = classic 7/14/28 Ultimate Oscillator: enter long when UO < entry (30),
exit to flat when UO > exit (70). Matches packages strategy UltimateOscReversion
and the matrix_strats2 'Ultimate 30/70' cell.

Validates against the real run_backtest engine on a ~6-week window, then sweeps
2024-01-01..2026-06-22 on AVAX/ADA/DOGE/BNB -USDT 15m across slippage levels.

  docker compose run --rm -w /app -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/vec_uo.py:/tmp/v.py \
    -v /home/signal/app/logs:/app/logs backtest_worker python /tmp/v.py
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np

from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.data.db import get_engine, get_sessionmaker
from packages.livetrade.bars import load_bars
from packages.strategy.resolver import resolve_strategy

TF = "15m"
FEE_BPS = 10.0
BARS_PER_YEAR = 365 * 24 * 4   # 15m bars/yr
SYMS = ["AVAX", "ADA", "DOGE", "BNB"]
SLIPS = [5, 15, 25]
ENTRY, EXIT = 30.0, 70.0
STRAT_NAME = "Ultimate Osc Reversion 15m"
USER_EMAIL = "aliasfar2006@gmail.com"


def _roll_sum(a, w):
    """sum(a[i-w+1 .. i]) aligned at i; NaN before the window is full."""
    out = np.full(len(a), np.nan)
    if len(a) < w:
        return out
    c = np.cumsum(a)
    out[w - 1:] = c[w - 1:] - np.concatenate(([0.0], c[:-w]))
    return out


def _uo(h, l, c):
    """Vectorized Ultimate Oscillator (7/14/28). UO[i] valid once 28 bars deep."""
    pc = np.concatenate(([c[0]], c[:-1]))             # prev close (seed[0]=close[0])
    true_low = np.minimum(l, pc)
    bp = c - true_low
    tr = np.maximum(h, pc) - true_low
    out = np.full(len(c), np.nan)
    a = {}
    for k in (7, 14, 28):
        sbp = _roll_sum(bp, k)
        str_ = _roll_sum(tr, k)
        with np.errstate(invalid="ignore", divide="ignore"):
            a[k] = np.where(str_ > 0, sbp / str_, np.nan)
    uo = 100.0 * (4 * a[7] + 2 * a[14] + a[28]) / 7.0
    # first valid index needs prev_close too -> from i=28 onward
    return uo


def backtest(o, h, l, c, slip_bps, fee_bps=FEE_BPS, alloc=0.95):
    n = len(c)
    uo = _uo(h, l, c)
    enter = uo < ENTRY
    exitb = uo > EXIT
    slip = slip_bps / 1e4
    fee = fee_bps / 1e4
    cash = 10000.0
    qty = 0.0
    in_pos = False
    equity = np.empty(n)
    trades = wins = 0
    gross_win = gross_loss = 0.0
    entry_cost = 0.0
    for i in range(n):
        if i > 0:
            op = o[i]
            if not in_pos and enter[i - 1] and not math.isnan(uo[i - 1]):
                fill = op * (1 + slip)
                spend = cash * alloc
                qty = spend / fill
                cash -= spend + spend * fee
                entry_cost = spend * (1 + fee)
                in_pos = True
            elif in_pos and exitb[i - 1] and not math.isnan(uo[i - 1]):
                fill = op * (1 - slip)
                proceeds = qty * fill
                cash += proceeds - proceeds * fee
                pnl = proceeds * (1 - fee) - entry_cost
                trades += 1
                if pnl > 0:
                    wins += 1; gross_win += pnl
                else:
                    gross_loss += -pnl
                qty = 0.0
                in_pos = False
        equity[i] = cash + qty * c[i]
    final_eq = cash + qty * c[-1]
    ret = (final_eq / 10000.0 - 1) * 100
    peak = np.maximum.accumulate(equity)
    maxdd = ((equity - peak) / peak).min() * 100
    er = np.diff(equity) / equity[:-1]
    sd = er.std()
    sharpe = (er.mean() / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    return dict(ret=ret, maxdd=maxdd, sharpe=sharpe, n=trades,
                win=(100 * wins / trades if trades else 0.0), pf=pf)


async def load_np(engine, base, q, start, end):
    df = await load_bars(engine, f"{base}-{q}@BINANCEUS", TF, start=start, end=end)
    if df is None or df.empty:
        return None
    return (df["open"].to_numpy(float), df["high"].to_numpy(float),
            df["low"].to_numpy(float), df["close"].to_numpy(float))


async def main():
    engine = get_engine()
    sm = get_sessionmaker()
    async with sm() as s:
        uid = (await s.execute(__import__("sqlalchemy").text(
            "SELECT id FROM users WHERE email=:e"), {"e": USER_EMAIL})).scalar()

    # --- VALIDATION: vec vs real engine on a short window (real engine handles it) ---
    v0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    v1 = datetime(2026, 6, 23, tzinfo=timezone.utc)
    print("=== VALIDATION (vec vs real engine, 15m USDT, May1-Jun23) ===", flush=True)
    for base in SYMS:
        sym = f"{base}-USDT@BINANCEUS"
        o, h, l, c = await load_np(engine, base, "USDT", v0, v1)
        rv = backtest(o, h, l, c, slip_bps=5)
        df = await load_bars(engine, sym, TF, start=v0, end=v1)
        meta = await load_instrument_meta(engine, [sym])
        async with sm() as s:
            r = await resolve_strategy(s, user_id=uid, strategy_name=STRAT_NAME,
                                       builtin_registry={})
        strat = r.cls(symbols=[sym], params=r.cls.PARAMS_MODEL())
        res = run_backtest(strat, {sym: df}, BacktestConfig(
            starting_cash=Decimal("10000"), fee_rate_bps=10, slippage_bps=5,
            instrument_meta=meta))
        a = compute_analytics(res)
        print(f"  {base:5} vec={rv['ret']:+7.2f}% (trd {rv['n']})   "
              f"real={a.total_return_pct:+7.2f}% (trd {a.num_closed_trades})", flush=True)

    # --- 2-YEAR SWEEP ---
    s0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s1 = datetime(2026, 6, 22, tzinfo=timezone.utc)
    yrs = (s1 - s0).days / 365.25
    out = open("/app/logs/vec_uo_2yr.jsonl", "w")
    print(f"\n=== 2-YEAR SWEEP {s0.date()}..{s1.date()} ({yrs:.2f}y) 15m USDT ===", flush=True)
    print(f"{'sym':6}{'slip':>5}{'ret':>10}{'CAGR':>8}{'maxDD':>8}{'shrp':>6}"
          f"{'n':>6}{'/day':>6}{'win':>6}{'pf':>6}{'B&H':>9}", flush=True)
    for base in SYMS:
        data = await load_np(engine, base, "USDT", s0, s1)
        if data is None:
            print(f"{base:6} no bars", flush=True); continue
        o, h, l, c = data
        days = len(c) / (24 * 4)
        bh = (c[-1] / c[0] - 1) * 100
        for slip in SLIPS:
            r = backtest(o, h, l, c, slip)
            cagr = ((1 + r["ret"] / 100) ** (1 / yrs) - 1) * 100 if r["ret"] > -100 else -100
            tpd = r["n"] / days
            rec = dict(sym=base, slip=slip, bars=len(c), ret=r["ret"], cagr=cagr,
                       maxdd=r["maxdd"], sharpe=r["sharpe"], n=r["n"],
                       tpd=round(tpd, 2), win=r["win"], pf=r["pf"], bh=bh)
            print(f"{base:6}{slip:>5}{r['ret']:>+9.1f}%{cagr:>+7.1f}%{r['maxdd']:>+7.1f}%"
                  f"{r['sharpe']:>6.1f}{r['n']:>6}{tpd:>6.2f}{r['win']:>5.0f}%{r['pf']:>6.2f}"
                  f"{bh:>+8.1f}%", flush=True)
            out.write(json.dumps(rec, default=float) + "\n"); out.flush()
    out.close()
    await engine.dispose()
    print("\n-> logs/vec_uo_2yr.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
