"""OOS robustness check for the 5m Donchian-breakout survivors (BNB + DOGE).

The 50-strat matrix surfaced Donchian 20/10 @ 5m as net-positive in-sample on BOTH
BNB (+6.9%, pf2.42, 2.8/d) and DOGE (+5.4%, pf1.94, 2.8/d) — cross-sectional, ~couple
trades/day. This tests whether that survives out of sample across disjoint ~1-month
5m windows (same neighborhood: 20/10, 40/20, 55/20) before believing it.

  docker compose run --rm -w /app --name oos_donch \
    -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/matrix_strats.py:/tmp/ms.py \
    -v /home/signal/app/scripts/oos_donchian.py:/tmp/oos.py \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python /tmp/oos.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal

spec = importlib.util.spec_from_file_location("ms", "/tmp/ms.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta

TF = "15m"  # placeholder, overridden below
SYMBOLS = ["BNB-USDT@BINANCEUS", "DOGE-USDT@BINANCEUS"]
TF = "5m"

# disjoint ~1-month 5m windows; last is the original in-sample month
WINDOWS = [
    ("2025-12-15", "2026-01-15"),
    ("2026-01-15", "2026-02-15"),
    ("2026-02-15", "2026-03-15"),
    ("2026-03-15", "2026-04-15"),
    ("2026-04-15", "2026-05-15"),
    ("2026-05-15", "2026-06-15"),  # original IS
]
CANDIDATES = ["Donchian 20/10", "Donchian 40/20", "Donchian 55/20"]
SPECS = {name: (en, ex) for (name, fam, (en, ex)) in ms.SPECS}


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _g(x):
    return 0 if x is None else x


async def main():
    engine = get_engine()
    meta = await load_instrument_meta(engine, SYMBOLS)
    rows = []
    for sym in SYMBOLS:
        print(f"\n########## {sym.split('-')[0]} ##########", flush=True)
        for (a, b) in WINDOWS:
            df = await load_bars(engine, sym, TF, start=_dt(a), end=_dt(b))
            n = 0 if df is None else len(df)
            days = (_dt(b) - _dt(a)).days
            print(f"=== {a}..{b}  ({n} bars) ===", flush=True)
            for name in CANDIDATES:
                en, ex = SPECS[name]
                strat = ms.FuncStrat(symbols=[sym], params=ms._P())
                strat._enter, strat._exit = en, ex
                cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                     fee_rate_bps=10, slippage_bps=5,
                                     instrument_meta=meta)
                try:
                    res = run_backtest(strat, {sym: df}, cfg)
                    an = compute_analytics(res)
                    tpd = (an.num_closed_trades or 0) / days
                    rec = dict(sym=sym.split('-')[0], window=f"{a}..{b}", strat=name,
                               ret=an.total_return_pct, pf=an.profit_factor,
                               n=an.num_closed_trades, tpd=round(tpd, 2),
                               win=an.win_rate_pct, sharpe=an.sharpe_ratio)
                    print(f"  {name:16} ret={_g(rec['ret']):7.1f}%  pf={_g(rec['pf']):.2f}  "
                          f"n={_g(rec['n']):3}  {rec['tpd']:.2f}/d", flush=True)
                except Exception as e:
                    rec = dict(sym=sym.split('-')[0], window=f"{a}..{b}", strat=name,
                               error=f"{type(e).__name__}: {e}")
                    print(f"  {name:16} ERR {rec['error']}", flush=True)
                rows.append(rec)
    with open("/app/logs/oos_donchian.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=float) + "\n")
    await engine.dispose()
    print("\n-> logs/oos_donchian.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
