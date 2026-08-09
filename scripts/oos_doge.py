"""OOS robustness check for the DOGE 15m survivors.

Reuses the matrix module's strat builders + engine config. Runs the candidate
DOGE strategies across several DISJOINT ~3-month 15m windows to see whether the
in-sample edge (Mar15-Jun15 2026) persists out of sample or was regime luck.

  docker compose run --rm -w /app --name oos_doge \
    -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/matrix_strats.py:/tmp/ms.py \
    -v /home/signal/app/scripts/oos_doge.py:/tmp/oos.py \
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

SYMBOL = "DOGE-USDT@BINANCEUS"
TF = "15m"

# disjoint ~3-month windows; last is the original in-sample baseline
WINDOWS = [
    ("2025-06-15", "2025-09-15"),
    ("2025-09-15", "2025-12-15"),
    ("2025-12-15", "2026-03-15"),
    ("2026-03-15", "2026-06-15"),  # original IS
]

CANDIDATES = [
    "Stoch 14/3 10/90",
    "Stoch+RSI 20/35",
    "RSI14 30/70",
    "Stoch 14/3 20/80",  # neighbor, was negative IS -> sanity
]
SPECS = {name: (en, ex) for (name, fam, (en, ex)) in ms.SPECS}


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


async def main():
    engine = get_engine()
    meta = await load_instrument_meta(engine, [SYMBOL])
    rows = []
    for (a, b) in WINDOWS:
        df = await load_bars(engine, SYMBOL, TF, start=_dt(a), end=_dt(b))
        n = 0 if df is None else len(df)
        print(f"\n=== window {a}..{b}  ({n} bars) ===", flush=True)
        for name in CANDIDATES:
            en, ex = SPECS[name]
            strat = ms.FuncStrat(symbols=[SYMBOL], params=ms._P())
            strat._enter, strat._exit = en, ex
            cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                 fee_rate_bps=10, slippage_bps=5,
                                 instrument_meta=meta)
            try:
                res = run_backtest(strat, {SYMBOL: df}, cfg)
                an = compute_analytics(res)
                days = (_dt(b) - _dt(a)).days
                tpd = (an.num_closed_trades or 0) / days
                rec = dict(window=f"{a}..{b}", strat=name,
                           ret=an.total_return_pct, pf=an.profit_factor,
                           n=an.num_closed_trades, tpd=round(tpd, 2),
                           win=an.win_rate_pct, sharpe=an.sharpe_ratio)
            except Exception as e:
                rec = dict(window=f"{a}..{b}", strat=name, error=f"{type(e).__name__}: {e}")
            rows.append(rec)
            if "error" in rec:
                print(f"  {name:20} ERR {rec['error']}", flush=True)
            else:
                print(f"  {name:20} ret={_g(rec['ret']):7.1f}%  pf={_g(rec['pf']):.2f}  "
                      f"n={_g(rec['n']):3}  {rec['tpd']:.2f}/d  win={_g(rec['win'])}%", flush=True)
    with open("/app/logs/oos_doge.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=float) + "\n")
    await engine.dispose()
    print("\n-> logs/oos_doge.jsonl", flush=True)


def _g(x):
    return 0 if x is None else x


if __name__ == "__main__":
    asyncio.run(main())
