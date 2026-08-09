"""Buy-and-hold benchmark for the Donchian OOS windows — is it alpha or beta?

For each (symbol, 5m month) compute simple buy&hold return and time-in-market for
Donchian 20/10, so we can compare the strat's return vs just holding the asset.
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

SYMBOLS = ["BNB-USDT@BINANCEUS", "DOGE-USDT@BINANCEUS"]
TF = "5m"
WINDOWS = [
    ("2025-12-15", "2026-01-15"), ("2026-01-15", "2026-02-15"),
    ("2026-02-15", "2026-03-15"), ("2026-03-15", "2026-04-15"),
    ("2026-04-15", "2026-05-15"), ("2026-05-15", "2026-06-15"),
]
SPECS = {n: (en, ex) for (n, f, (en, ex)) in ms.SPECS}
STRAT = "Donchian 20/10"


def _dt(s): return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
def _g(x): return 0 if x is None else float(x)


async def main():
    engine = get_engine()
    meta = await load_instrument_meta(engine, SYMBOLS)
    print(f"{'sym':5}{'window':16}{'B&H':>9}{'Donch':>9}{'alpha':>9}{'trades':>8}")
    for sym in SYMBOLS:
        for (a, b) in WINDOWS:
            df = await load_bars(engine, sym, TF, start=_dt(a), end=_dt(b))
            if df is None or df.empty:
                continue
            c0, c1 = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
            bh = (c1 - c0) / c0 * 100
            en, ex = SPECS[STRAT]
            strat = ms.FuncStrat(symbols=[sym], params=ms._P())
            strat._enter, strat._exit = en, ex
            cfg = BacktestConfig(starting_cash=Decimal("10000"), fee_rate_bps=10,
                                 slippage_bps=5, instrument_meta=meta)
            an = compute_analytics(run_backtest(strat, {sym: df}, cfg))
            d = _g(an.total_return_pct)
            print(f"{sym.split('-')[0]:5}{a[5:]+'..'+b[5:]:16}{bh:>+8.1f}%{d:>+8.1f}%"
                  f"{d-bh:>+8.1f}%{_g(an.num_closed_trades):>8.0f}", flush=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
