"""Backtest a curated set of strategies and emit real stats as JSON.

Run inside the backtest_worker image (has deps + DB access + baked packages):

  docker compose run --rm -T -w /app \
    -v /home/signal/app/scripts/build_catalog_strategies.py:/tmp/bcs.py \
    backtest_worker python /tmp/bcs.py

Each strategy is long-flat and sizes positions as ~95% of account equity at
entry (so returns are meaningful, not the old 0.01-unit no-op). Stats come from
the same engine + analytics the worker uses, so they're real.
"""
from __future__ import annotations

import asyncio
import json
import sys

from pydantic import BaseModel, Field

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


# ----------------------------- sizing helper -----------------------------
def _enter_full(self, ctx: BarContext, symbol: str) -> None:
    price = ctx.close(symbol)
    if price is None or float(price) <= 0:
        return
    cash = ctx.cash
    qty = (float(cash) * 0.95) / float(price)
    if qty > 0:
        ctx.submit_buy_market(symbol, qty)


def _exit_full(self, ctx: BarContext, symbol: str) -> None:
    pos = ctx.position(symbol)
    if float(pos) > 0:
        ctx.submit_sell_market(symbol, pos)


# ----------------------------- param models ------------------------------
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


# ----------------------------- the 20 strategies -------------------------
# (cls, name, slug, strategy_type, asset_class, symbol, timeframe, params)
SPECS = [
    (SMACross,    "BTC Trend Rider",          "btc-trend-rider",        "trend",          "crypto", "BTC-USDT@BINANCEUS", "1h", dict(a=20, b=50)),
    (EMACross,    "ETH Momentum EMA",         "eth-momentum-ema",       "trend",          "crypto", "ETH-USDT@BINANCEUS", "1h", dict(a=12, b=26)),
    (RSIMeanRev,  "SOL Dip Buyer",            "sol-dip-buyer",          "mean_reversion", "crypto", "SOL-USDT@BINANCEUS", "1h", dict(period=14, lo=30, hi=55)),
    (BollingerMR, "BTC Band Fade",            "btc-band-fade",          "mean_reversion", "crypto", "BTC-USDT@BINANCEUS", "1h", dict(period=20)),
    (MACDTrend,   "ETH MACD Trend",           "eth-macd-trend",         "trend",          "crypto", "ETH-USDT@BINANCEUS", "1h", dict(a=12, b=26, period=9)),
    (Donchian,    "BTC Breakout 55",          "btc-breakout-55",        "breakout",       "crypto", "BTC-USDT@BINANCEUS", "1h", dict(a=55, b=20)),
    (Momentum,    "SOL 24h Momentum",         "sol-24h-momentum",       "momentum",       "crypto", "SOL-USDT@BINANCEUS", "1h", dict(n=24, thr=0.03)),
    (RSIMeanRev,  "LINK Oversold Bounce",     "link-oversold-bounce",   "mean_reversion", "crypto", "LINK-USDT@BINANCEUS","1h", dict(period=14, lo=25, hi=60)),
    (EMACross,    "AVAX Fast EMA",            "avax-fast-ema",          "trend",          "crypto", "AVAX-USDT@BINANCEUS","1h", dict(a=9, b=21)),
    (SMACross,    "ADA Slow Trend",           "ada-slow-trend",         "trend",          "crypto", "ADA-USDT@BINANCEUS", "1h", dict(a=10, b=40)),
    (BollingerMR, "DOGE Band Fade",           "doge-band-fade",         "mean_reversion", "crypto", "DOGE-USDT@BINANCEUS","1h", dict(period=20)),
    (MACDTrend,   "XRP MACD Swing",           "xrp-macd-swing",         "trend",          "crypto", "XRP-USDT@BINANCEUS", "1h", dict(a=12, b=26, period=9)),
    (SMACross,    "SPY Golden Cross",         "spy-golden-cross",       "trend",          "stocks", "SPY@ALPACA",  "1h", dict(a=50, b=200)),
    (EMACross,    "QQQ Trend EMA",            "qqq-trend-ema",          "trend",          "stocks", "QQQ@ALPACA",  "1h", dict(a=12, b=26)),
    (RSIMeanRev,  "AAPL Pullback",            "aapl-pullback",          "mean_reversion", "stocks", "AAPL@ALPACA", "1h", dict(period=14, lo=30, hi=55)),
    (Donchian,    "NVDA Breakout",            "nvda-breakout",          "breakout",       "stocks", "NVDA@ALPACA", "1h", dict(a=40, b=20)),
    (Momentum,    "TSLA Momentum",            "tsla-momentum",          "momentum",       "stocks", "TSLA@ALPACA", "1h", dict(n=24, thr=0.04)),
    (BollingerMR, "MSFT Band Fade",           "msft-band-fade",         "mean_reversion", "stocks", "MSFT@ALPACA", "1h", dict(period=20)),
    (MACDTrend,   "AMZN MACD Trend",          "amzn-macd-trend",        "trend",          "stocks", "AMZN@ALPACA", "1h", dict(a=12, b=26, period=9)),
    (RSIMeanRev,  "SPY Mean Reversion",       "spy-mean-reversion",     "mean_reversion", "stocks", "SPY@ALPACA",  "1h", dict(period=14, lo=35, hi=65)),
]


async def main() -> None:
    engine = get_engine()
    out = []
    for cls, name, slug, stype, ac, symbol, tf, params in SPECS:
        rec = {"slug": slug, "name": name, "strategy_type": stype,
               "asset_class": ac, "symbol": symbol, "timeframe": tf, "params": params}
        try:
            # Cap to a recent window — full 12-18k-bar history is far slower to
            # load+iterate and a ~6k-bar window (≈8 months crypto / ~2y stock RTH)
            # gives statistically meaningful stats much faster.
            df = await load_bars(engine, symbol, tf, limit=6000)
            if df is None or df.empty:
                rec["error"] = "no bars"
                out.append(rec); continue
            meta = await load_instrument_meta(engine, [symbol])
            strat = cls(symbols=[symbol], params=XParams(**params))
            cfg = BacktestConfig(starting_cash=__import__("decimal").Decimal("10000"),
                                 fee_rate_bps=10, slippage_bps=5, instrument_meta=meta)
            result = run_backtest(strat, {symbol: df}, cfg)
            a = compute_analytics(result)
            rec["window"] = [str(df.index[0].date()), str(df.index[-1].date())]
            rec["bars"] = len(df)
            rec["stats"] = {
                "total_return_pct": a.total_return_pct,
                "annualized_return_pct": a.annualized_return_pct,
                "sharpe": a.sharpe_ratio,
                "sortino": a.sortino_ratio,
                "max_drawdown_pct": a.max_drawdown_pct,
                "calmar": a.calmar_ratio,
                "num_trades": a.num_closed_trades,
                "win_rate_pct": a.win_rate_pct,
                "profit_factor": a.profit_factor,
                "avg_winner_pct": a.avg_winner_pct,
                "avg_loser_pct": a.avg_loser_pct,
            }
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"
        out.append(rec)
        print(f"  done: {slug}", file=sys.stderr)
    await engine.dispose()
    print(json.dumps(out, default=float))


if __name__ == "__main__":
    asyncio.run(main())
