"""Comprehensive validation of the Donchian-breakout 5m edge.

Runs in ONE continuous 6-month window (2025-12-15 .. 2026-06-15) per symbol so
max_drawdown is the TRUE stitched drawdown, not month-reset. Covers:
  - full 8-symbol universe (generalization)
  - slippage stress 5 / 15 / 25 bps on the primary 20/10 (cost robustness)
  - neighborhood 40/20 + 55/20 at realistic 15bps
  - buy&hold benchmark per symbol (alpha vs beta)

Streams one JSON row per (symbol, strat, slip) to logs/donchian_full.jsonl.

  docker compose run --rm -d -w /app --name donch_full \
    -e PYTHONPATH=/app \
    -v /home/signal/app/scripts/matrix_strats.py:/tmp/ms.py \
    -v /home/signal/app/scripts/donchian_full.py:/tmp/df.py \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python /tmp/df.py
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
BASES = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]
# also probe live-tradable USD pairs for the two known-good names
USD_PROBE = ["BNB-USD@BINANCEUS", "DOGE-USD@BINANCEUS"]
SPECS = {n: (en, ex) for (n, f, (en, ex)) in ms.SPECS}
STRATS = ["Donchian 20/10", "Donchian 40/20", "Donchian 55/20"]
SLIPS = [5, 15, 25]
OUT = "/app/logs/donchian_full.jsonl"


def _g(x):
    return 0 if x is None else float(x)


def run_one(sym, df, meta, strat_name, slip):
    en, ex = SPECS[strat_name]
    strat = ms.FuncStrat(symbols=[sym], params=ms._P())
    strat._enter, strat._exit = en, ex
    cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=10,
                         slippage_bps=slip, instrument_meta=meta)
    an = compute_analytics(run_backtest(strat, {sym: df}, cfg))
    return an


async def main():
    engine = get_engine()
    out = open(OUT, "w")
    allsyms = [f"{b}-USDT@BINANCEUS" for b in BASES] + USD_PROBE
    meta = await load_instrument_meta(engine, allsyms)
    print(f"{'sym':16}{'strat':16}{'slip':>5}{'ret':>9}{'maxDD':>8}{'shrp':>6}"
          f"{'n':>5}{'/day':>6}{'B&H':>8}", flush=True)
    for sym in allsyms:
        t0 = time.time()
        df = await load_bars(engine, sym, TF, start=START, end=END)
        n = 0 if df is None else len(df)
        if df is None or df.empty:
            print(f"{sym:16}  -- no bars --", flush=True)
            out.write(json.dumps({"sym": sym, "error": "no bars"}) + "\n"); out.flush()
            continue
        c0, c1 = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
        bh = (c1 - c0) / c0 * 100
        print(f"# {sym} loaded {n} bars in {time.time()-t0:.0f}s (B&H {bh:+.1f}%)", flush=True)
        for st in STRATS:
            for slip in SLIPS:
                # full slip sweep only for primary 20/10; others at 15bps only
                if st != "Donchian 20/10" and slip != 15:
                    continue
                t1 = time.time()
                try:
                    an = run_one(sym, df, meta, st, slip)
                    tpd = _g(an.num_closed_trades) / DAYS
                    rec = {"sym": sym, "strat": st, "slip": slip, "bars": n,
                           "ret": _g(an.total_return_pct), "maxdd": _g(an.max_drawdown_pct),
                           "sharpe": _g(an.sharpe_ratio), "n": int(_g(an.num_closed_trades)),
                           "tpd": round(tpd, 2), "win": _g(an.win_rate_pct),
                           "pf": _g(an.profit_factor), "bh": bh, "secs": round(time.time()-t1, 1)}
                    print(f"{sym:16}{st:16}{slip:>5}{rec['ret']:>+8.1f}%{rec['maxdd']:>+7.1f}%"
                          f"{rec['sharpe']:>6.1f}{rec['n']:>5}{rec['tpd']:>6.2f}{bh:>+7.1f}%", flush=True)
                except Exception as e:
                    rec = {"sym": sym, "strat": st, "slip": slip, "error": f"{type(e).__name__}: {e}"}
                    print(f"{sym:16}{st:16}{slip:>5}  ERR {e}", flush=True)
                out.write(json.dumps(rec, default=float) + "\n"); out.flush()
    out.close()
    await engine.dispose()
    print(f"\n-> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
