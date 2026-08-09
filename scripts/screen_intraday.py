"""Fast vectorized screen for net-of-cost regime-reversion edge across the
crypto universe and {5m,10m,15m,30m,1h} timeframes.

Honest, engine-faithful:
  * Indicators use the platform's OWN packages.strategy.indicators (exact RSI
    Wilder / SMA) so scanner readings == real-engine readings.
  * Fills replicate packages/backtest/fills.py: a decision taken on bar t's
    CLOSE fills at bar t+1's OPEN, buy*(1+slip) / sell*(1-slip); fee_bps on
    notional each side. tp/sl trigger on close (matches the deployed strategy,
    which checks px=close), exit fills next-open. NO intrabar look-ahead.

Why vectorized, not the real queue: the per-(symbol,res) Strategy/BarContext
engine recomputes indicators over full history every bar (O(n^2)) — unusable
for a universe sweep. This screens; survivors then get validated on the real
engine (which this is calibrated against). See memory no-1m-edge-cost-wall.

Run inside a one-off api container with scripts/ mounted:
  docker compose run --rm --no-deps -v /home/signal/app/scripts:/app/scripts api \
    python /app/scripts/screen_intraday.py
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import numpy as np
import asyncpg

from packages.strategy import indicators  # exact-match RSI/SMA

RES_TABLE = {
    "5m": "cagg_bars_5m", "10m": "cagg_bars_10m", "15m": "cagg_bars_15m",
    "30m": "cagg_bars_30m", "1h": "cagg_bars_1h",
}
BARS_PER_WEEK = {"5m": 2016, "10m": 1008, "15m": 672, "30m": 336, "1h": 168}

SYMS = ("BTC,ETH,SOL,XRP,DOGE,ADA,AVAX,LINK,LTC,BNB,DOT,ATOM,UNI,AAVE,NEAR,BCH,"
        "ETC,XLM,ALGO,FIL,ICP,HBAR,INJ,APT,ARB,OP,POL,SUI,RENDER,FET,SHIB,PEPE")
SYMBOLS = [f"{s}-USDT@BINANCEUS" for s in SYMS.split(",")]
TFS = ["1h", "30m", "15m", "10m", "5m"]

IS_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 7, 1, tzinfo=timezone.utc)

# (tag, rsi, sma, lo, le, hi, se, tp, sl, long_only)
# hi/se ignored when long_only. Covers the proven region + faster/higher-freq.
GRID = [
    ("pro_link",   14, 200, 42, 60, 0,  0,  0.040, 0.06, True),
    ("pro_ls",     14, 200, 43, 55, 57, 45, 0.030, 0.06, False),
    ("pro_bnb",    14, 200, 42, 55, 0,  0,  0.030, 0.05, True),
    ("deepdip",    14, 200, 35, 55, 0,  0,  0.030, 0.05, True),
    ("sma100",     14, 100, 42, 60, 0,  0,  0.030, 0.05, True),
    ("sma100_ls",  14, 100, 40, 58, 60, 42, 0.025, 0.04, False),
    ("rsi7_f",      7, 100, 35, 60, 0,  0,  0.020, 0.03, True),
    ("rsi7_200",    7, 200, 30, 60, 0,  0,  0.025, 0.04, True),
    ("hf_tight",   14, 200, 45, 55, 0,  0,  0.020, 0.03, True),
    ("rsi7_ls",     7, 100, 30, 65, 70, 35, 0.020, 0.03, False),
    ("sma50_f",    14,  50, 40, 60, 0,  0,  0.030, 0.05, True),
    ("connors2",    2, 100, 10, 55, 0,  0,  0.020, 0.03, True),
    ("connors2b",   2, 200, 15, 60, 0,  0,  0.025, 0.04, True),
    ("scalp",      14, 200, 48, 52, 0,  0,  0.015, 0.025, True),
]

COSTS = [(5, 3), (10, 5)]  # (fee_bps, slip_bps) per side; 16bps & 30bps RT


async def load_bars(conn, symbol, res):
    rows = await conn.fetch(
        f"SELECT c.bucket, c.open, c.high, c.low, c.close FROM {RES_TABLE[res]} c "
        f"JOIN instruments i ON i.id=c.instrument_id "
        f"WHERE i.canonical_symbol=$1 AND c.bucket>=$2 AND c.bucket<$3 ORDER BY c.bucket",
        symbol, IS_START, OOS_END,
    )
    if not rows:
        return None
    ts = np.array([r["bucket"] for r in rows])
    o = np.array([float(r["open"]) for r in rows])
    c = np.array([float(r["close"]) for r in rows])
    return ts, o, c


def simulate(ts, o, c, rsi, sma, cfg, fee_bps, slip_bps, win_start, win_end):
    """Return (ret_pct, pf, win_pct, n_trades, maxdd_pct). Decisions on close[t],
    fills at open[t+1]. Position sized at 90% of cash."""
    _, rsi_p, sma_p, lo, le, hi, se, tp, sl, long_only = cfg
    fee = fee_bps / 1e4
    slip = slip_bps / 1e4
    n = len(c)
    cash = 10000.0
    pos = 0.0          # signed units
    entry_px = 0.0
    equity_peak = cash
    maxdd = 0.0
    wins = gross_win = gross_loss = 0.0
    n_trades = 0
    realized_cost_basis = 0.0  # cash spent entering current position (incl fees)

    in_win = (ts >= np.datetime64(win_start)) & (ts < np.datetime64(win_end))
    warm = max(rsi_p + 1, sma_p) + 1

    for t in range(warm, n - 1):
        if not in_win[t]:
            continue
        r = rsi[t]; sv = sma[t]; px = c[t]
        if np.isnan(r) or np.isnan(sv) or px <= 0:
            continue
        fill_open = o[t + 1]
        if fill_open <= 0:
            continue
        if pos == 0:
            do_long = (r < lo) and (px > sv)
            do_short = (not long_only) and (r > hi) and (px < sv)
            if do_long:
                fp = fill_open * (1 + slip)
                qty = (0.90 * cash) / fp
                cost = qty * fp * (1 + fee)
                cash -= cost
                pos = qty; entry_px = fp; realized_cost_basis = cost
            elif do_short:
                fp = fill_open * (1 - slip)
                qty = (0.90 * cash) / fp
                proceeds = qty * fp * (1 - fee)
                cash += proceeds
                pos = -qty; entry_px = fp; realized_cost_basis = proceeds
        elif pos > 0:
            tp_hit = tp > 0 and px >= entry_px * (1 + tp)
            sl_hit = sl > 0 and px <= entry_px * (1 - sl)
            if r > le or tp_hit or sl_hit:
                fp = fill_open * (1 - slip)
                proceeds = pos * fp * (1 - fee)
                cash += proceeds
                pnl = proceeds - realized_cost_basis
                n_trades += 1
                if pnl > 0: wins += 1; gross_win += pnl
                else: gross_loss += -pnl
                pos = 0.0
        else:  # short
            tp_hit = tp > 0 and px <= entry_px * (1 - tp)
            sl_hit = sl > 0 and px >= entry_px * (1 + sl)
            if r < se or tp_hit or sl_hit:
                fp = fill_open * (1 + slip)
                cost = (-pos) * fp * (1 + fee)
                cash -= cost
                pnl = realized_cost_basis - cost
                n_trades += 1
                if pnl > 0: wins += 1; gross_win += pnl
                else: gross_loss += -pnl
                pos = 0.0
        # mark-to-market equity for drawdown
        eq = cash + pos * c[t]
        if eq > equity_peak: equity_peak = eq
        if equity_peak > 0:
            dd = (eq - equity_peak) / equity_peak
            if dd < maxdd: maxdd = dd

    # close any open position at last in-window close
    final_eq = cash + pos * c[min(n - 1, np.where(in_win)[0][-1] if in_win.any() else n - 1)]
    ret_pct = (final_eq / 10000.0 - 1) * 100
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    win_pct = (wins / n_trades * 100) if n_trades else 0.0
    return ret_pct, pf, win_pct, n_trades, maxdd * 100


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    survivors = []
    portfolio_1h = []
    try:
        for symbol in SYMBOLS:
            for tf in TFS:
                loaded = await load_bars(conn, symbol, tf)
                if loaded is None:
                    continue
                ts, o, c = loaded
                if len(c) < 500:
                    continue
                import pandas as pd
                cs = pd.Series(c)
                rsi_cache = {}
                sma_cache = {}
                for cfg in GRID:
                    _, rsi_p, sma_p = cfg[0], cfg[1], cfg[2]
                    if rsi_p not in rsi_cache:
                        rsi_cache[rsi_p] = indicators.rsi(cs, rsi_p).to_numpy()
                    if sma_p not in sma_cache:
                        sma_cache[sma_p] = indicators.sma(cs, sma_p).to_numpy()
                    rsi = rsi_cache[rsi_p]; sma = sma_cache[sma_p]
                    for fee_bps, slip_bps in COSTS:
                        is_r = simulate(ts, o, c, rsi, sma, cfg, fee_bps, slip_bps, IS_START, OOS_START)
                        # only spend OOS sim if IS is positive at this cost
                        if is_r[0] <= 0 or is_r[3] < 4:
                            continue
                        oos = simulate(ts, o, c, rsi, sma, cfg, fee_bps, slip_bps, OOS_START, OOS_END)
                        rec = {
                            "sym": symbol.split("@")[0], "tf": tf, "cfg": cfg[0],
                            "cost": f"{fee_bps}/{slip_bps}",
                            "is_ret": is_r[0], "is_pf": is_r[1], "is_n": is_r[3],
                            "oos_ret": oos[0], "oos_pf": oos[1], "oos_win": oos[2],
                            "oos_n": oos[3], "oos_dd": oos[4],
                            "tpw": oos[3] / max(1, (OOS_END - OOS_START).days / 7),
                        }
                        # survivor = positive & pf>=1.15 in BOTH IS and OOS
                        if (is_r[0] > 0 and is_r[1] >= 1.15 and oos[0] > 0
                                and oos[1] >= 1.15 and oos[3] >= 4):
                            survivors.append(rec)
                        if tf == "1h" and fee_bps == 5:
                            portfolio_1h.append(rec)
                print(f"done {symbol.split('@')[0]:6} {tf}", flush=True)
    finally:
        await conn.close()

    def show(rows, title):
        print(f"\n{'='*100}\n{title} ({len(rows)})\n{'='*100}")
        print(f"{'sym':10}{'tf':4}{'cfg':11}{'cost':6}{'ISret':>8}{'ISpf':>6}{'ISn':>5}"
              f"{'OOSret':>8}{'OOSpf':>6}{'OOSwin':>7}{'OOSn':>5}{'OOSdd':>7}{'tpw':>6}")
        for r in rows:
            print(f"{r['sym']:10}{r['tf']:4}{r['cfg']:11}{r['cost']:6}"
                  f"{r['is_ret']:8.1f}{r['is_pf']:6.2f}{r['is_n']:5d}"
                  f"{r['oos_ret']:8.1f}{r['oos_pf']:6.2f}{r['oos_win']:7.0f}"
                  f"{r['oos_n']:5d}{r['oos_dd']:7.1f}{r['tpw']:6.1f}")

    survivors.sort(key=lambda r: r["oos_ret"], reverse=True)
    show(survivors, "NET-OF-COST SURVIVORS (IS+OOS positive, pf>=1.15)")
    show([r for r in survivors if r["cost"] == "10/5"],
         "ROBUST SURVIVORS @ conservative 30bps RT (10/5)")
    portfolio_1h.sort(key=lambda r: r["oos_ret"], reverse=True)
    show([r for r in portfolio_1h if r["oos_ret"] > 0][:40],
         "1h PORTFOLIO CANDIDATES @16bps (OOS positive, top 40)")


if __name__ == "__main__":
    asyncio.run(main())
