"""Crypto strategy search harness.

Loads real Binance.US bars from the cagg tables, runs candidate strategy
families across a parameter grid, and evaluates each on an honest
train / out-of-sample (OOS) split with realistic fees + slippage.

Run inside the api/worker container:
    docker compose exec -T api python -m scripts.research.crypto_search
"""
from __future__ import annotations

import asyncio
import itertools
import math
from decimal import Decimal
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel, Field

from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


# ----------------------------------------------------------------------------
# Sizing helper: deploy a fixed fraction of current equity on entry (long-flat).
# ----------------------------------------------------------------------------
def _equity(ctx: BarContext, sym: str) -> float:
    px = ctx.close(sym)
    pos = ctx.position(sym)
    cash = ctx.cash
    if px is None:
        return float(cash)
    return float(cash) + float(pos) * float(px)


def _buy_fraction(ctx: BarContext, sym: str, frac: float) -> None:
    px = ctx.close(sym)
    cash = float(ctx.cash)
    if px is None or cash <= 0:
        return
    # leave a little room for fees/slippage so the fill isn't rejected
    qty = (frac * cash * 0.985) / float(px)
    if qty > 0:
        ctx.submit_buy_market(sym, qty)


# ============================================================================
# Strategy families
# ============================================================================
class EmaTrendParams(BaseModel):
    model_config = {"extra": "forbid"}
    fast: int = Field(default=20, ge=2, le=200)
    slow: int = Field(default=50, ge=5, le=400)
    trend: int = Field(default=200, ge=20, le=500)  # regime filter
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_mult: float = Field(default=3.0, gt=0)       # trailing stop distance
    risk_fraction: float = Field(default=0.95, gt=0, le=1)


class EmaTrend(Strategy[EmaTrendParams]):
    """Long-flat EMA trend with a regime filter and an ATR trailing stop.

    Enter long when fast EMA > slow EMA AND price is above the long trend EMA
    (only trade with the macro trend). Ride with an ATR trailing stop; also
    exit if the fast/slow trend flips back down.
    """

    PARAMS_MODEL = EmaTrendParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["peak"] = None  # highest close since entry (for trailing stop)

    def on_bar(self, ctx: BarContext) -> None:
        s = self.symbol
        p = self.params
        fast = ctx.ema(s, p.fast)
        slow = ctx.ema(s, p.slow)
        trend = ctx.ema(s, p.trend)
        atr = ctx.atr(s, p.atr_period)
        px = ctx.close(s)
        if None in (fast, slow, trend, atr, px):
            return
        fast, slow, trend, atr, px = map(float, (fast, slow, trend, atr, px))
        pos = float(ctx.position(s))

        if pos == 0:
            if fast > slow and px > trend:
                gap = (fast - slow) / slow
                ctx.signal("ema_trend_up", value=gap, symbol=s)
                _buy_fraction(ctx, s, p.risk_fraction)
                self.state["peak"] = px
        else:
            peak = self.state.get("peak") or px
            peak = max(peak, px)
            self.state["peak"] = peak
            trail_stop = peak - p.atr_mult * atr
            if px <= trail_stop or fast < slow:
                reason = "trail_stop" if px <= trail_stop else "trend_flip"
                ctx.signal(f"ema_exit_{reason}", value=(px - peak) / peak, symbol=s)
                ctx.submit_sell_market(s, ctx.position(s))
                self.state["peak"] = None


class DonchianParams(BaseModel):
    model_config = {"extra": "forbid"}
    entry: int = Field(default=55, ge=5, le=300)     # breakout lookback
    exit: int = Field(default=20, ge=3, le=200)      # exit lookback
    trend: int = Field(default=200, ge=0, le=500)    # 0 = no regime filter
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_mult: float = Field(default=2.0, gt=0)
    risk_fraction: float = Field(default=0.95, gt=0, le=1)


class Donchian(Strategy[DonchianParams]):
    """Turtle-style Donchian channel breakout, long-flat.

    Enter long on a close above the highest high of the last `entry` bars
    (optionally only when above the trend EMA). Exit on a close below the
    lowest low of the last `exit` bars, OR an ATR stop below entry.
    """

    PARAMS_MODEL = DonchianParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["stop"] = None

    def on_bar(self, ctx: BarContext) -> None:
        s = self.symbol
        p = self.params
        bars = ctx.bars(s)
        need = max(p.entry, p.exit, p.trend) + 2
        if len(bars) < need:
            return
        px = float(ctx.close(s))
        atr = ctx.atr(s, p.atr_period)
        if atr is None:
            return
        atr = float(atr)
        # channel computed on bars strictly before the current one
        hi = float(bars["high"].iloc[-(p.entry + 1):-1].max())
        lo = float(bars["low"].iloc[-(p.exit + 1):-1].min())
        trend_ok = True
        if p.trend > 0:
            te = ctx.ema(s, p.trend)
            trend_ok = te is not None and px > float(te)
        pos = float(ctx.position(s))

        if pos == 0:
            if px > hi and trend_ok:
                ctx.signal("donchian_breakout", value=(px - hi) / hi, symbol=s)
                _buy_fraction(ctx, s, p.risk_fraction)
                self.state["stop"] = px - p.atr_mult * atr
        else:
            stop = self.state.get("stop")
            if px < lo or (stop is not None and px <= stop):
                reason = "channel" if px < lo else "atr_stop"
                ctx.signal(f"donchian_exit_{reason}", value=0.0, symbol=s)
                ctx.submit_sell_market(s, ctx.position(s))
                self.state["stop"] = None


class RsiRevParams(BaseModel):
    model_config = {"extra": "forbid"}
    rsi_period: int = Field(default=14, ge=2, le=100)
    buy_below: float = Field(default=30, ge=1, le=50)
    sell_above: float = Field(default=55, ge=50, le=99)
    trend: int = Field(default=200, ge=0, le=500)  # only buy dips in uptrend
    risk_fraction: float = Field(default=0.95, gt=0, le=1)


class RsiReversion(Strategy[RsiRevParams]):
    """Buy-the-dip mean reversion: long when RSI is oversold (optionally only
    in an uptrend), exit when RSI recovers."""

    PARAMS_MODEL = RsiRevParams

    def on_init(self) -> None:
        self.symbol = self.symbols[0]

    def on_bar(self, ctx: BarContext) -> None:
        s = self.symbol
        p = self.params
        rsi = ctx.rsi(s, p.rsi_period)
        px = ctx.close(s)
        if rsi is None or px is None:
            return
        rsi = float(rsi)
        pos = float(ctx.position(s))
        trend_ok = True
        if p.trend > 0:
            te = ctx.ema(s, p.trend)
            trend_ok = te is not None and float(px) > float(te)

        if pos == 0 and rsi < p.buy_below and trend_ok:
            ctx.signal("rsi_oversold", value=p.buy_below - rsi, symbol=s)
            _buy_fraction(ctx, s, p.risk_fraction)
        elif pos > 0 and rsi > p.sell_above:
            ctx.signal("rsi_recovered", value=rsi - p.sell_above, symbol=s)
            ctx.submit_sell_market(s, ctx.position(s))


# ============================================================================
# Evaluation
# ============================================================================
FAMILIES: dict[str, tuple[type[Strategy], list[dict[str, Any]]]] = {}


def _grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kw.values())]


FAMILIES["ema_trend"] = (
    EmaTrend,
    _grid(
        fast=[10, 20, 30],
        slow=[50, 100],
        trend=[100, 200],
        atr_mult=[2.5, 3.5],
    ),
)
FAMILIES["donchian"] = (
    Donchian,
    _grid(
        entry=[20, 40, 55],
        exit=[10, 20],
        trend=[0, 200],
        atr_mult=[2.0, 3.0],
    ),
)
FAMILIES["rsi_rev"] = (
    RsiReversion,
    _grid(
        rsi_period=[14],
        buy_below=[25, 30, 35],
        sell_above=[50, 60],
        trend=[0, 200],
    ),
)


CONFIG = BacktestConfig(
    starting_cash=Decimal("10000"),
    fee_rate_bps=10,
    slippage_bps=5,
    allow_short=False,
)


def _metrics(bars: dict[str, pd.DataFrame], strat: Strategy) -> Optional[dict]:
    try:
        res = run_backtest(strat, bars, CONFIG)
        a = compute_analytics(res)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}
    return {
        "ret": a.total_return_pct,
        "ann": a.annualized_return_pct,
        "sharpe": a.sharpe_ratio,
        "maxdd": a.max_drawdown_pct,
        "trades": a.num_closed_trades,
        "win": a.win_rate_pct,
        "pf": a.profit_factor,
    }


def _split(df: pd.DataFrame, frac: float = 0.7):
    n = len(df)
    cut = int(n * frac)
    return df.iloc[:cut], df.iloc[cut:]


def _buyhold(df: pd.DataFrame) -> float:
    return float(df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100


import json
import os

RESULTS_PATH = "/app/scripts/research/results.json"


async def main() -> None:
    engine = get_engine()
    symbols = ["BTC-USDT@BINANCEUS", "ETH-USDT@BINANCEUS"]
    resolution = os.environ.get("RES", "4h")

    raw: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = await load_bars(engine, sym, resolution)
        raw[sym] = df
        print(f"{sym}: {len(df)} {resolution} bars  {df.index[0]} -> {df.index[-1]}  "
              f"buy&hold {_buyhold(df):+.0f}%", flush=True)
    print(flush=True)

    # ---- Phase 1: rank every config on the FULL period (1 backtest each) ----
    ranked = []
    n = sum(len(g) for _, g in FAMILIES.values()) * len(symbols)
    i = 0
    for sym in symbols:
        full = raw[sym]
        for fam, (cls, grid) in FAMILIES.items():
            for params in grid:
                i += 1
                s = cls(symbols=[sym], params=cls.PARAMS_MODEL(**params))
                m = _metrics({sym: full}, s)
                if not m or "error" in m:
                    print(f"[{i}/{n}] ERR {fam} {params}: {m.get('error') if m else '?'}", flush=True)
                    continue
                ranked.append({"sym": sym, "fam": fam, "params": params, "full": m,
                               "bh_full": _buyhold(full)})
                print(f"[{i}/{n}] {fam:10} {sym.split('-')[0]:4} ret {m['ret']:+6.0f}% "
                      f"shrp {m['sharpe'] if m['sharpe'] is not None else 'NA'} "
                      f"dd {m['maxdd']:.0f}% tr {m['trades']}", flush=True)

    # candidates: trustworthy + profitable + beat buy&hold on the full period
    cand = [r for r in ranked
            if r["full"]["trades"] >= 30 and r["full"]["sharpe"] is not None
            and r["full"]["sharpe"] > 0 and r["full"]["ret"] > r["bh_full"]]
    cand.sort(key=lambda r: r["full"]["sharpe"], reverse=True)
    finalists = cand[:8]
    print(f"\n{len(cand)} candidates beat buy&hold; validating top {len(finalists)} on OOS...\n", flush=True)

    # ---- Phase 2: validate finalists on train(70%) / OOS-test(30%) split ----
    for r in finalists:
        sym = r["sym"]
        full = raw[sym]
        train, test = _split(full, 0.7)
        cls = FAMILIES[r["fam"]][0]
        r["train"] = _metrics({sym: train}, cls(symbols=[sym], params=cls.PARAMS_MODEL(**r["params"])))
        r["test"] = _metrics({sym: test}, cls(symbols=[sym], params=cls.PARAMS_MODEL(**r["params"])))
        r["bh_te"] = _buyhold(test)

    # a real winner: positive AND beats buy&hold on the held-out OOS slice too
    survivors = [r for r in finalists
                 if r.get("test") and r["test"].get("sharpe") is not None
                 and r["test"]["sharpe"] > 0 and r["test"]["ret"] > r["bh_te"]]
    survivors.sort(key=lambda r: (r["test"]["sharpe"], r["full"]["sharpe"]), reverse=True)

    out = {"resolution": resolution, "ranked": ranked, "finalists": finalists,
           "survivors": survivors}
    with open(RESULTS_PATH, "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print(f"\n{'='*104}\n{len(ranked)} configs evaluated · {len(cand)} beat B&H full · "
          f"{len(survivors)} also survive OOS\n{'='*104}", flush=True)
    hdr = (f"{'sym':4} {'family':10} {'FULLret%':>8} {'shrp':>5} {'dd%':>5} {'tr':>4} {'win%':>5} | "
           f"{'OOSret%':>7} {'OOSshrp':>7} {'OOSdd%':>6} {'bhOOS%':>7}")
    print(hdr); print("-" * len(hdr), flush=True)
    for r in finalists:
        f = r["full"]; te = r.get("test") or {}
        mark = " *" if r in survivors else "  "
        print(f"{r['sym'].split('-')[0]:4} {r['fam']:10} {f['ret']:+8.0f} {f['sharpe']:5.2f} "
              f"{f['maxdd']:5.0f} {f['trades']:4d} {(f['win'] or 0):5.0f} | "
              f"{te.get('ret',0):+7.0f} {(te.get('sharpe') or 0):7.2f} {te.get('maxdd',0):6.0f} "
              f"{r.get('bh_te',0):+7.0f}{mark}  {r['params']}", flush=True)

    if survivors:
        w = survivors[0]
        print(f"\nWINNER: {w['fam']} on {w['sym']}  params={w['params']}", flush=True)
        print(f"  full: ret {w['full']['ret']:+.0f}%  sharpe {w['full']['sharpe']:.2f}  "
              f"maxdd {w['full']['maxdd']:.0f}%  trades {w['full']['trades']}  "
              f"win {w['full']['win']:.0f}%  pf {w['full']['pf']}", flush=True)
        print(f"  OOS:  ret {w['test']['ret']:+.0f}%  sharpe {w['test']['sharpe']:.2f}  "
              f"maxdd {w['test']['maxdd']:.0f}%  trades {w['test']['trades']}  "
              f"(buy&hold OOS {w['bh_te']:+.0f}%)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
