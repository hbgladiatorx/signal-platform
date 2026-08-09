"""Deep slippage stress on the SLOWER Donchian breakouts (40/20, 55/20) — the real
candidates after 20/10 proved too fast to survive realistic cost.

Continuous 6-month window, all 8 USDT majors + USD probes, slip in 5/15/25/35 bps.
Finds the breaking point of the slow breakout. Streams to logs/donchian_slow.jsonl.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from datetime import datetime, timezone
from decimal import Decimal

spec = importlib.util.spec_from_file_location("ms", "/tmp/ms.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta

TF = "5m"
START = datetime(2025, 12, 15, tzinfo=timezone.utc)
END = datetime(2026, 6, 15, tzinfo=timezone.utc)
DAYS = (END - START).days
SYMS = [f"{b}-USDT@BINANCEUS" for b in
        ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]] + \
       ["BNB-USD@BINANCEUS", "DOGE-USD@BINANCEUS"]
SPECS = {n: (en, ex) for (n, f, (en, ex)) in ms.SPECS}
STRATS = ["Donchian 40/20", "Donchian 55/20"]
SLIPS = [5, 15, 25, 35]
OUT = "/app/logs/donchian_slow.jsonl"


def _g(x): return 0 if x is None else float(x)


async def main():
    engine = get_engine()
    out = open(OUT, "w")
    meta = await load_instrument_meta(engine, SYMS)
    print(f"{'sym':16}{'strat':16}{'slip':>5}{'ret':>9}{'maxDD':>8}{'shrp':>6}{'n':>5}{'/day':>6}{'B&H':>8}", flush=True)
    for sym in SYMS:
        df = await load_bars(engine, sym, TF, start=START, end=END)
        if df is None or df.empty:
            print(f"{sym:16}  -- no bars --", flush=True)
            out.write(json.dumps({"sym": sym, "error": "no bars"}) + "\n"); out.flush(); continue
        c0, c1 = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
        bh = (c1 - c0) / c0 * 100
        for st in STRATS:
            en, ex = SPECS[st]
            for slip in SLIPS:
                strat = ms.FuncStrat(symbols=[sym], params=ms._P())
                strat._enter, strat._exit = en, ex
                cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=10,
                                     slippage_bps=slip, instrument_meta=meta)
                try:
                    an = compute_analytics(run_backtest(strat, {sym: df}, cfg))
                    rec = {"sym": sym, "strat": st, "slip": slip,
                           "ret": _g(an.total_return_pct), "maxdd": _g(an.max_drawdown_pct),
                           "sharpe": _g(an.sharpe_ratio), "n": int(_g(an.num_closed_trades)),
                           "tpd": round(_g(an.num_closed_trades)/DAYS, 2),
                           "pf": _g(an.profit_factor), "bh": bh}
                    print(f"{sym:16}{st:16}{slip:>5}{rec['ret']:>+8.1f}%{rec['maxdd']:>+7.1f}%"
                          f"{rec['sharpe']:>6.1f}{rec['n']:>5}{rec['tpd']:>6.2f}{bh:>+7.1f}%", flush=True)
                except Exception as e:
                    rec = {"sym": sym, "strat": st, "slip": slip, "error": str(e)}
                    print(f"{sym:16}{st:16}{slip:>5}  ERR {e}", flush=True)
                out.write(json.dumps(rec, default=float) + "\n"); out.flush()
    out.close(); await engine.dispose()
    print(f"\n-> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
