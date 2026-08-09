"""5m strategy x ticker matrix PILOT.

Crosses 21 strategy archetypes (7 base classes from build_catalog_strategies,
spread across fast+slow params) against the top-8 liquid crypto tickers at 5m,
to find any strategy family that survives the 5m cost wall before scaling to a
full 50 x 28 matrix.

Runs IN-PROCESS via run_backtest (same engine the worker uses) -- no job queue,
so all cells run serially in one container with no 20-min-per-job overhead.

Run inside the backtest_worker image (deps + DB + baked packages):

  docker compose run --rm -T -w /app \
    -v /home/signal/app/scripts/matrix_5m_pilot.py:/tmp/m5.py \
    backtest_worker python /tmp/m5.py

Env knobs (for calibration):
  MATRIX_MAX_CELLS=N   stop after N cells (timing probe)
  MATRIX_SYMBOLS=...   comma-sep base tickers override (default top-8)

Results stream to logs/matrix_5m_pilot.jsonl (one row per cell) so progress is
queryable mid-run and a crash loses nothing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext

# 1-month window: this host is 2-core/3GB running 11 live containers, and the
# engine runs ~200 bars/sec, so the matrix must run single-container. 1mo
# (~8.6k 5m bars) still yields hundreds of trades/cell -- plenty to expose the
# cost wall -- and keeps 168 cells to ~2hr instead of ~11hr.
WIN_START = datetime(2026, 5, 15, tzinfo=timezone.utc)
WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)

# Per-symbol output (so parallel containers don't clobber one file).
OUT_PATH = os.environ.get("MATRIX_OUT", "/app/logs/matrix_5m_pilot.jsonl")

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]
QUOTE = "-USDT@BINANCEUS"  # the deep-history 5m pairs


# ----------------------------- sizing helpers ----------------------------
def _enter_full(self, ctx: BarContext, symbol: str) -> None:
    price = ctx.close(symbol)
    if price is None or float(price) <= 0:
        return
    qty = (float(ctx.cash) * 0.95) / float(price)
    if qty > 0:
        ctx.submit_buy_market(symbol, qty)


def _exit_full(self, ctx: BarContext, symbol: str) -> None:
    pos = ctx.position(symbol)
    if float(pos) > 0:
        ctx.submit_sell_market(symbol, pos)


# ----------------------------- params + base -----------------------------
class XParams(BaseModel):
    model_config = {"extra": "allow"}
    a: int = Field(default=10)
    b: int = Field(default=30)
    lo: float = Field(default=30.0)
    hi: float = Field(default=60.0)
    period: int = Field(default=14)
    n: int = Field(default=20)
    thr: float = Field(default=0.0)


class _Base(Strategy[XParams]):
    PARAMS_MODEL = XParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]


class SMACross(_Base):
    def on_bar(self, ctx):
        f = ctx.sma(self.symbol, self.params.a)
        s = ctx.sma(self.symbol, self.params.b)
        if f is None or s is None:
            return
        pos = float(ctx.position(self.symbol))
        if f > s and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif f < s and pos > 0:
            _exit_full(self, ctx, self.symbol)


class EMACross(_Base):
    def on_bar(self, ctx):
        f = ctx.ema(self.symbol, self.params.a)
        s = ctx.ema(self.symbol, self.params.b)
        if f is None or s is None:
            return
        pos = float(ctx.position(self.symbol))
        if f > s and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif f < s and pos > 0:
            _exit_full(self, ctx, self.symbol)


class RSIMeanRev(_Base):
    def on_bar(self, ctx):
        r = ctx.rsi(self.symbol, self.params.period)
        if r is None:
            return
        r = float(r)
        pos = float(ctx.position(self.symbol))
        if r < self.params.lo and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif r > self.params.hi and pos > 0:
            _exit_full(self, ctx, self.symbol)


class BollingerMR(_Base):
    def on_bar(self, ctx):
        b = ctx.bollinger(self.symbol, self.params.period)
        c = ctx.close(self.symbol)
        if b is None or c is None:
            return
        c = float(c)
        pos = float(ctx.position(self.symbol))
        if c < float(b.lower) and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif c >= float(b.mid) and pos > 0:
            _exit_full(self, ctx, self.symbol)


class MACDTrend(_Base):
    def on_bar(self, ctx):
        m = ctx.macd(self.symbol, self.params.a, self.params.b, self.params.period)
        if m is None:
            return
        pos = float(ctx.position(self.symbol))
        if float(m.macd) > float(m.signal) and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif float(m.macd) < float(m.signal) and pos > 0:
            _exit_full(self, ctx, self.symbol)


class Donchian(_Base):
    def on_bar(self, ctx):
        df = ctx.bars(self.symbol)
        if df is None or len(df) < self.params.a + 2:
            return
        c = float(df["close"].iloc[-1])
        hi = float(df["high"].iloc[-(self.params.a + 1):-1].max())
        lo = float(df["low"].iloc[-(self.params.b + 1):-1].min())
        pos = float(ctx.position(self.symbol))
        if c > hi and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif c < lo and pos > 0:
            _exit_full(self, ctx, self.symbol)


class Momentum(_Base):
    def on_bar(self, ctx):
        df = ctx.bars(self.symbol)
        if df is None or len(df) < self.params.n + 2:
            return
        c = float(df["close"].iloc[-1])
        past = float(df["close"].iloc[-(self.params.n + 1)])
        if past <= 0:
            return
        ret = (c - past) / past
        pos = float(ctx.position(self.symbol))
        if ret > self.params.thr and pos == 0:
            _enter_full(self, ctx, self.symbol)
        elif ret < 0 and pos > 0:
            _exit_full(self, ctx, self.symbol)


# ----------------------------- 21 archetypes -----------------------------
# (cls, name, family, params) -- spread of fast+slow params per family so the
# pilot isn't biased to 1h-tuned windows.
STRATS = [
    (SMACross,    "SMA 20/50",        "trend-sma",  dict(a=20, b=50)),
    (SMACross,    "SMA 10/40",        "trend-sma",  dict(a=10, b=40)),
    (SMACross,    "SMA 50/200",       "trend-sma",  dict(a=50, b=200)),
    (EMACross,    "EMA 12/26",        "trend-ema",  dict(a=12, b=26)),
    (EMACross,    "EMA 9/21",         "trend-ema",  dict(a=9, b=21)),
    (EMACross,    "EMA 20/50",        "trend-ema",  dict(a=20, b=50)),
    (RSIMeanRev,  "RSI 14 30/55",     "mr-rsi",     dict(period=14, lo=30, hi=55)),
    (RSIMeanRev,  "RSI 14 25/60",     "mr-rsi",     dict(period=14, lo=25, hi=60)),
    (RSIMeanRev,  "RSI 14 35/65",     "mr-rsi",     dict(period=14, lo=35, hi=65)),
    (RSIMeanRev,  "RSI 7 25/55",      "mr-rsi",     dict(period=7,  lo=25, hi=55)),
    (BollingerMR, "Bollinger 20",     "mr-bb",      dict(period=20)),
    (BollingerMR, "Bollinger 50",     "mr-bb",      dict(period=50)),
    (MACDTrend,   "MACD 12/26/9",     "trend-macd", dict(a=12, b=26, period=9)),
    (MACDTrend,   "MACD 8/21/5",      "trend-macd", dict(a=8,  b=21, period=5)),
    (Donchian,    "Donchian 55/20",   "breakout",   dict(a=55, b=20)),
    (Donchian,    "Donchian 40/20",   "breakout",   dict(a=40, b=20)),
    (Donchian,    "Donchian 20/10",   "breakout",   dict(a=20, b=10)),
    (Momentum,    "Mom 24 / 3%",      "momentum",   dict(n=24, thr=0.03)),
    (Momentum,    "Mom 24 / 4%",      "momentum",   dict(n=24, thr=0.04)),
    (Momentum,    "Mom 12 / 2%",      "momentum",   dict(n=12, thr=0.02)),
    (Momentum,    "Mom 48 / 5%",      "momentum",   dict(n=48, thr=0.05)),
]


async def main() -> None:
    max_cells = int(os.environ.get("MATRIX_MAX_CELLS", "0")) or None
    bases = os.environ.get("MATRIX_SYMBOLS")
    bases = bases.split(",") if bases else DEFAULT_SYMBOLS
    symbols = [f"{b}{QUOTE}" for b in bases]

    engine = get_engine()
    # Cache bars + meta per symbol so we load each symbol's 5m history once.
    bar_cache: dict[str, object] = {}
    meta_cache: dict[str, object] = {}

    out = open(OUT_PATH, "w")
    cells = 0
    t_all = time.time()
    for symbol in symbols:
        if symbol not in bar_cache:
            t0 = time.time()
            df = await load_bars(engine, symbol, "5m", start=WIN_START, end=WIN_END)
            bar_cache[symbol] = df
            meta_cache[symbol] = await load_instrument_meta(engine, [symbol])
            print(f"[load] {symbol}: {0 if df is None else len(df)} bars "
                  f"in {time.time()-t0:.1f}s", file=sys.stderr, flush=True)
        df = bar_cache[symbol]
        meta = meta_cache[symbol]
        for cls, sname, family, params in STRATS:
            if max_cells and cells >= max_cells:
                break
            rec = {"symbol": symbol, "strategy": sname, "family": family,
                   "params": params, "timeframe": "5m"}
            t0 = time.time()
            try:
                if df is None or df.empty:
                    rec["error"] = "no bars"
                else:
                    strat = cls(symbols=[symbol], params=XParams(**params))
                    cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                         fee_rate_bps=10, slippage_bps=5,
                                         instrument_meta=meta)
                    result = run_backtest(strat, {symbol: df}, cfg)
                    a = compute_analytics(result)
                    rec["bars"] = len(df)
                    rec["stats"] = {
                        "total_return_pct": a.total_return_pct,
                        "sharpe": a.sharpe_ratio,
                        "max_drawdown_pct": a.max_drawdown_pct,
                        "num_trades": a.num_closed_trades,
                        "win_rate_pct": a.win_rate_pct,
                        "profit_factor": a.profit_factor,
                    }
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["secs"] = round(time.time() - t0, 1)
            out.write(json.dumps(rec, default=float) + "\n")
            out.flush()
            cells += 1
            r = rec.get("stats", {}).get("total_return_pct")
            print(f"[cell {cells}] {symbol} | {sname}: "
                  f"{'ERR ' + rec['error'] if 'error' in rec else f'{r:+.1f}%'} "
                  f"({rec['secs']}s)", file=sys.stderr, flush=True)
        if max_cells and cells >= max_cells:
            break
    out.close()
    await engine.dispose()
    print(f"[done] {cells} cells in {time.time()-t_all:.1f}s -> {OUT_PATH}",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
