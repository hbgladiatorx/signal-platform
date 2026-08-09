"""50-strategy x ticker x timeframe matrix.

Crosses 50 DISTINCT strategy archetypes (14 indicator families, not just param
tweaks) against the top-8 liquid crypto tickers, on BOTH 5m and 15m, to map
which (if any) strategy family beats the intraday cost wall.

Runs in-process via run_backtest (same engine the worker uses). Single
container -- this host is 2-core/3GB running 11 live containers, so no fan-out.

  docker compose run --rm -d -w /app --name m_strats \
    -e MATRIX_OUT=/app/logs/matrix_strats.jsonl \
    -v /home/signal/app/scripts/matrix_strats.py:/tmp/ms.py \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python /tmp/ms.py

Window is sized PER TIMEFRAME to hold bar-count ~constant (~8.6k bars => equal
trade mass + equal engine cost per cell): 5m->1mo, 15m->3mo.
Results stream to logs/matrix_strats.jsonl, one row per (tf, symbol, strategy).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel

from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext

WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
# (timeframe, window_start) -- ~8.6k bars each. MATRIX_TF env (e.g. "15m" or
# "5m,15m") restricts which run; default both.
_ALL_TF = {
    "5m": datetime(2026, 5, 15, tzinfo=timezone.utc),   # 1 month
    "15m": datetime(2026, 3, 15, tzinfo=timezone.utc),  # 3 months
}
_sel = os.environ.get("MATRIX_TF", "5m,15m").split(",")
TIMEFRAMES = [(tf, _ALL_TF[tf]) for tf in _sel if tf in _ALL_TF]
DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX"]
QUOTE = "-USDT@BINANCEUS"
OUT_PATH = os.environ.get("MATRIX_OUT", "/app/logs/matrix_strats.jsonl")


# ----------------------------- sizing helpers ----------------------------
def _enter_full(ctx: BarContext, symbol: str) -> None:
    price = ctx.close(symbol)
    if price is None or float(price) <= 0:
        return
    qty = (float(ctx.cash) * 0.95) / float(price)
    if qty > 0:
        ctx.submit_buy_market(symbol, qty)


def _exit_full(ctx: BarContext, symbol: str) -> None:
    pos = ctx.position(symbol)
    if float(pos) > 0:
        ctx.submit_sell_market(symbol, pos)


def _f(x):
    return None if x is None else float(x)


# --------------------- strategy = (enter_fn, exit_fn) --------------------
# Each factory returns (enter, exit); both take (ctx, symbol) -> bool. Long-flat.

def ma_cross(fast, slow, kind):
    def en(ctx, s): return ctx.crossed_above(s, fast, slow, kind) is True
    def ex(ctx, s): return ctx.crossed_below(s, fast, slow, kind) is True
    return en, ex


def price_vs_ma(period, kind):  # trend-follow: hold while price > MA
    fn = (lambda ctx, s, p: ctx.ema(s, p)) if kind == "ema" else (lambda ctx, s, p: ctx.sma(s, p))
    def en(ctx, s):
        m, c = _f(fn(ctx, s, period)), _f(ctx.close(s))
        return m is not None and c is not None and c > m
    def ex(ctx, s):
        m, c = _f(fn(ctx, s, period)), _f(ctx.close(s))
        return m is not None and c is not None and c < m
    return en, ex


def macd_cross(fast, slow, sig):
    def en(ctx, s):
        m = ctx.macd(s, fast, slow, sig); return m is not None and m.crossed_up
    def ex(ctx, s):
        m = ctx.macd(s, fast, slow, sig); return m is not None and m.crossed_down
    return en, ex


def macd_hist(fast, slow, sig):
    def en(ctx, s):
        m = ctx.macd(s, fast, slow, sig); return m is not None and float(m.hist) > 0
    def ex(ctx, s):
        m = ctx.macd(s, fast, slow, sig); return m is not None and float(m.hist) < 0
    return en, ex


def roc(n, thr):
    def _r(ctx, s):
        df = ctx.bars(s)
        if df is None or len(df) < n + 1:
            return None
        c, p = float(df["close"].iloc[-1]), float(df["close"].iloc[-(n + 1)])
        return (c - p) / p if p > 0 else None
    def en(ctx, s):
        r = _r(ctx, s); return r is not None and r > thr
    def ex(ctx, s):
        r = _r(ctx, s); return r is not None and r < 0
    return en, ex


def rsi_mr(period, lo, hi):
    def en(ctx, s):
        r = _f(ctx.rsi(s, period)); return r is not None and r < lo
    def ex(ctx, s):
        r = _f(ctx.rsi(s, period)); return r is not None and r > hi
    return en, ex


def stoch_mr(k, d, lo, hi):
    def en(ctx, s):
        st = ctx.stoch(s, k, d); return st is not None and float(st.k) < lo
    def ex(ctx, s):
        st = ctx.stoch(s, k, d); return st is not None and float(st.k) > hi
    return en, ex


def bb_fade(period, nstd):  # mean-reversion: buy lower band, sell mid
    def en(ctx, s):
        b, c = ctx.bollinger(s, period, nstd), _f(ctx.close(s))
        return b is not None and c is not None and c < float(b.lower)
    def ex(ctx, s):
        b, c = ctx.bollinger(s, period, nstd), _f(ctx.close(s))
        return b is not None and c is not None and c >= float(b.mid)
    return en, ex


def bb_breakout(period, nstd):  # trend: buy upper band break, sell mid
    def en(ctx, s):
        b, c = ctx.bollinger(s, period, nstd), _f(ctx.close(s))
        return b is not None and c is not None and c > float(b.upper)
    def ex(ctx, s):
        b, c = ctx.bollinger(s, period, nstd), _f(ctx.close(s))
        return b is not None and c is not None and c < float(b.mid)
    return en, ex


def vwap_revert(period, band):
    def en(ctx, s):
        v, c = _f(ctx.vwap(s, period)), _f(ctx.close(s))
        return v is not None and c is not None and c < v * (1 - band)
    def ex(ctx, s):
        v, c = _f(ctx.vwap(s, period)), _f(ctx.close(s))
        return v is not None and c is not None and c > v
    return en, ex


def vwap_trend(period):
    def en(ctx, s):
        v, c = _f(ctx.vwap(s, period)), _f(ctx.close(s))
        return v is not None and c is not None and c > v
    def ex(ctx, s):
        v, c = _f(ctx.vwap(s, period)), _f(ctx.close(s))
        return v is not None and c is not None and c < v
    return en, ex


def donchian(up, dn):
    def en(ctx, s):
        df = ctx.bars(s)
        if df is None or len(df) < up + 2:
            return False
        return float(df["close"].iloc[-1]) > float(df["high"].iloc[-(up + 1):-1].max())
    def ex(ctx, s):
        df = ctx.bars(s)
        if df is None or len(df) < dn + 2:
            return False
        return float(df["close"].iloc[-1]) < float(df["low"].iloc[-(dn + 1):-1].min())
    return en, ex


def atr_mr(ema_p, mult):  # buy mult*ATR below EMA, exit back to EMA
    def en(ctx, s):
        e, a, c = _f(ctx.ema(s, ema_p)), _f(ctx.atr(s, 14)), _f(ctx.close(s))
        return None not in (e, a, c) and c < e - mult * a
    def ex(ctx, s):
        e, c = _f(ctx.ema(s, ema_p)), _f(ctx.close(s))
        return None not in (e, c) and c >= e
    return en, ex


def atr_breakout(ema_p, mult):  # Keltner-style trend break
    def en(ctx, s):
        e, a, c = _f(ctx.ema(s, ema_p)), _f(ctx.atr(s, 14)), _f(ctx.close(s))
        return None not in (e, a, c) and c > e + mult * a
    def ex(ctx, s):
        e, c = _f(ctx.ema(s, ema_p)), _f(ctx.close(s))
        return None not in (e, c) and c < e
    return en, ex


# ---- multi-indicator combos ----
def rsi_trend(period, lo, hi, trend_p):  # dip-buy ONLY in uptrend
    def en(ctx, s):
        r, m, c = _f(ctx.rsi(s, period)), _f(ctx.sma(s, trend_p)), _f(ctx.close(s))
        return None not in (r, m, c) and r < lo and c > m
    def ex(ctx, s):
        r = _f(ctx.rsi(s, period)); return r is not None and r > hi
    return en, ex


def bb_rsi(period, rsi_lo):
    def en(ctx, s):
        b, c, r = ctx.bollinger(s, period), _f(ctx.close(s)), _f(ctx.rsi(s, 14))
        return b is not None and c is not None and r is not None and c < float(b.lower) and r < rsi_lo
    def ex(ctx, s):
        b, c = ctx.bollinger(s, period), _f(ctx.close(s))
        return b is not None and c is not None and c >= float(b.mid)
    return en, ex


def macd_rsi(fast, slow, sig, rsi_cap):
    def en(ctx, s):
        m, r = ctx.macd(s, fast, slow, sig), _f(ctx.rsi(s, 14))
        return m is not None and r is not None and m.crossed_up and r < rsi_cap
    def ex(ctx, s):
        m = ctx.macd(s, fast, slow, sig); return m is not None and m.crossed_down
    return en, ex


def stoch_rsi(k, d, k_lo, rsi_lo):
    def en(ctx, s):
        st, r = ctx.stoch(s, k, d), _f(ctx.rsi(s, 14))
        return st is not None and r is not None and float(st.k) < k_lo and r < rsi_lo
    def ex(ctx, s):
        st = ctx.stoch(s, k, d); return st is not None and float(st.k) > 80
    return en, ex


def triple_ema(a, b, c):
    def en(ctx, s):
        ea, eb, ec = _f(ctx.ema(s, a)), _f(ctx.ema(s, b)), _f(ctx.ema(s, c))
        return None not in (ea, eb, ec) and ea > eb > ec
    def ex(ctx, s):
        ea, eb = _f(ctx.ema(s, a)), _f(ctx.ema(s, b))
        return None not in (ea, eb) and ea < eb
    return en, ex


def dual_mom(n1, n2):
    r1, _ = roc(n1, 0.0); r2, _ = roc(n2, 0.0)
    def _ret(ctx, s, n):
        df = ctx.bars(s)
        if df is None or len(df) < n + 1:
            return None
        c, p = float(df["close"].iloc[-1]), float(df["close"].iloc[-(n + 1)])
        return (c - p) / p if p > 0 else None
    def en(ctx, s):
        a, b = _ret(ctx, s, n1), _ret(ctx, s, n2)
        return a is not None and b is not None and a > 0 and b > 0
    def ex(ctx, s):
        a = _ret(ctx, s, n1); return a is not None and a < 0
    return en, ex


def vwap_bb(period):
    def en(ctx, s):
        v, c, b = _f(ctx.vwap(s, period)), _f(ctx.close(s)), ctx.bollinger(s, 20)
        return None not in (v, c) and b is not None and c < v and c < float(b.lower)
    def ex(ctx, s):
        v, c = _f(ctx.vwap(s, period)), _f(ctx.close(s))
        return None not in (v, c) and c > v
    return en, ex


# ------------------------------ the 50 -----------------------------------
# (name, family, (enter, exit))
SPECS = [
    # trend / MA cross (7)
    ("SMA cross 9/21",     "trend-ma",   ma_cross(9, 21, "sma")),
    ("SMA cross 20/50",    "trend-ma",   ma_cross(20, 50, "sma")),
    ("SMA cross 50/200",   "trend-ma",   ma_cross(50, 200, "sma")),
    ("EMA cross 9/21",     "trend-ma",   ma_cross(9, 21, "ema")),
    ("EMA cross 12/26",    "trend-ma",   ma_cross(12, 26, "ema")),
    ("EMA cross 20/50",    "trend-ma",   ma_cross(20, 50, "ema")),
    ("EMA cross 8/34",     "trend-ma",   ma_cross(8, 34, "ema")),
    # price vs MA (3)
    ("Price>SMA200",       "trend-pma",  price_vs_ma(200, "sma")),
    ("Price>EMA50",        "trend-pma",  price_vs_ma(50, "ema")),
    ("Price>EMA100",       "trend-pma",  price_vs_ma(100, "ema")),
    # MACD (5)
    ("MACD cross 12/26/9", "macd",       macd_cross(12, 26, 9)),
    ("MACD cross 8/21/5",  "macd",       macd_cross(8, 21, 5)),
    ("MACD cross 5/13/4",  "macd",       macd_cross(5, 13, 4)),
    ("MACD hist 12/26/9",  "macd",       macd_hist(12, 26, 9)),
    ("MACD hist 8/21/5",   "macd",       macd_hist(8, 21, 5)),
    # ROC momentum (4)
    ("ROC 12 / 1%",        "momentum",   roc(12, 0.01)),
    ("ROC 24 / 2%",        "momentum",   roc(24, 0.02)),
    ("ROC 48 / 3%",        "momentum",   roc(48, 0.03)),
    ("ROC 96 / 5%",        "momentum",   roc(96, 0.05)),
    # RSI mean-rev (6)
    ("RSI14 30/70",        "mr-rsi",     rsi_mr(14, 30, 70)),
    ("RSI14 25/60",        "mr-rsi",     rsi_mr(14, 25, 60)),
    ("RSI14 35/65",        "mr-rsi",     rsi_mr(14, 35, 65)),
    ("RSI14 40/60",        "mr-rsi",     rsi_mr(14, 40, 60)),
    ("RSI7 20/55",         "mr-rsi",     rsi_mr(7, 20, 55)),
    ("RSI21 35/65",        "mr-rsi",     rsi_mr(21, 35, 65)),
    # stochastic (4)
    ("Stoch 14/3 20/80",   "mr-stoch",   stoch_mr(14, 3, 20, 80)),
    ("Stoch 21/5 25/75",   "mr-stoch",   stoch_mr(21, 5, 25, 75)),
    ("Stoch 5/3 20/80",    "mr-stoch",   stoch_mr(5, 3, 20, 80)),
    ("Stoch 14/3 10/90",   "mr-stoch",   stoch_mr(14, 3, 10, 90)),
    # bollinger (5)
    ("BB fade 20/2",       "mr-bb",      bb_fade(20, 2.0)),
    ("BB fade 20/1.5",     "mr-bb",      bb_fade(20, 1.5)),
    ("BB fade 50/2",       "mr-bb",      bb_fade(50, 2.0)),
    ("BB breakout 20/2",   "breakout",   bb_breakout(20, 2.0)),
    ("BB breakout 20/1.5", "breakout",   bb_breakout(20, 1.5)),
    # vwap (3)
    ("VWAP revert 50/1%",  "vwap",       vwap_revert(50, 0.01)),
    ("VWAP revert 100/2%", "vwap",       vwap_revert(100, 0.02)),
    ("VWAP trend 50",      "vwap",       vwap_trend(50)),
    # donchian breakout (4)
    ("Donchian 10/5",      "breakout",   donchian(10, 5)),
    ("Donchian 20/10",     "breakout",   donchian(20, 10)),
    ("Donchian 40/20",     "breakout",   donchian(40, 20)),
    ("Donchian 55/20",     "breakout",   donchian(55, 20)),
    # atr bands (3)
    ("ATR-MR e20 x2",      "vol-atr",    atr_mr(20, 2.0)),
    ("ATR-MR e20 x2.5",    "vol-atr",    atr_mr(20, 2.5)),
    ("ATR-breakout e20 x1.5", "vol-atr", atr_breakout(20, 1.5)),
    # combos (6)
    ("RSI+trend 30/60 s200", "combo",    rsi_trend(14, 30, 60, 200)),
    ("BB+RSI 20 / r35",    "combo",      bb_rsi(20, 35)),
    ("MACD+RSI<70",        "combo",      macd_rsi(12, 26, 9, 70)),
    ("Stoch+RSI 20/35",    "combo",      stoch_rsi(14, 3, 20, 35)),
    ("Triple-EMA 8/21/55", "combo",      triple_ema(8, 21, 55)),
    ("Dual-mom 24/96",     "combo",      dual_mom(24, 96)),
    ("VWAP+BB revert",     "combo",      vwap_bb(50)),
]


class _P(BaseModel):
    model_config = {"extra": "allow"}


class FuncStrat(Strategy[_P]):
    PARAMS_MODEL = _P

    def on_init(self) -> None:
        self.symbol = self.symbols[0]

    def on_bar(self, ctx) -> None:
        s = self.symbol
        try:
            pos = float(ctx.position(s))
            if pos == 0:
                if self._enter(ctx, s):
                    _enter_full(ctx, s)
            else:
                if self._exit(ctx, s):
                    _exit_full(ctx, s)
        except Exception:  # noqa: BLE001 -- one bad bar shouldn't kill the cell
            return


async def main() -> None:
    bases = os.environ.get("MATRIX_SYMBOLS")
    bases = bases.split(",") if bases else DEFAULT_SYMBOLS
    symbols = [f"{b}{QUOTE}" for b in bases]
    max_cells = int(os.environ.get("MATRIX_MAX_CELLS", "0")) or None

    engine = get_engine()
    out = open(OUT_PATH, "w")
    cells = 0
    t_all = time.time()
    for tf, start in TIMEFRAMES:
        for symbol in symbols:
            t0 = time.time()
            df = await load_bars(engine, symbol, tf, start=start, end=WIN_END)
            meta = await load_instrument_meta(engine, [symbol])
            n = 0 if df is None else len(df)
            print(f"[load] {tf} {symbol}: {n} bars in {time.time()-t0:.1f}s",
                  file=sys.stderr, flush=True)
            for name, family, (en, ex) in SPECS:
                if max_cells and cells >= max_cells:
                    break
                rec = {"tf": tf, "symbol": symbol, "strategy": name, "family": family}
                t0 = time.time()
                try:
                    if df is None or df.empty:
                        rec["error"] = "no bars"
                    else:
                        strat = FuncStrat(symbols=[symbol], params=_P())
                        strat._enter, strat._exit = en, ex
                        cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                             fee_rate_bps=10, slippage_bps=5,
                                             instrument_meta=meta)
                        result = run_backtest(strat, {symbol: df}, cfg)
                        a = compute_analytics(result)
                        rec["bars"] = n
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
                tag = "ERR " + rec["error"] if "error" in rec else f"{r:+.1f}%"
                print(f"[{cells}] {tf} {symbol.split('-')[0]} | {name}: {tag} ({rec['secs']}s)",
                      file=sys.stderr, flush=True)
            if max_cells and cells >= max_cells:
                break
        if max_cells and cells >= max_cells:
            break
    out.close()
    await engine.dispose()
    print(f"[done] {cells} cells in {time.time()-t_all:.1f}s -> {OUT_PATH}",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
