"""Phase-1 A/B harness for the slow LLM meta-layer.

Question (pure go/no-go): does throttling the proven 1h mean-reversion book by an
LLM-decided gross_exposure BEAT the same book at fixed exposure=1.0, OUT OF SAMPLE?

Design:
  - Base strategy = the proven RSI(14) mean-reversion + SMA200 long-only regime
    filter (identical logic to scripts/screen_crypto_2yr.py), spot-realistic.
  - The ONLY lever the meta-layer pulls is ENTRY SIZING: new-entry qty is scaled
    by gross_exposure in [0,1]. Exits follow the base rules untouched. One clean
    causal lever => an honest read on whether the LLM adds value.
  - CONTROL = exposure pinned 1.0 (byte-identical to the base strategy).
    TREATMENT = exposure from meta_regime (LLM, or rule if META_MOCK=1).
  - One continuous 2yr run each (preserves SMA200/RSI warmup); OOS robustness read
    per calendar segment off the equity curve. No look-ahead: a decision at bar i
    is applied only to bars with ts strictly greater than i's ts.

Run inside the backtest_worker container (has DB creds + anthropic + key):
  docker compose run --rm -w /app -e PYTHONPATH=/app [-e META_MOCK=1] \
    backtest_worker python scripts/meta_ab.py
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from packages.backtest.analytics import compute_analytics
from packages.backtest.engine import run_backtest
from packages.backtest.types import BacktestConfig
from packages.data.db import get_engine
from packages.livetrade.bars import load_bars
from packages.strategy.base import Strategy
from packages.strategy.context import BarContext

from meta_regime import RegimeDecision, compute_regime_timeline

# The 28 Binance.US spot pairs with verified full 2-year 1h coverage
# (same universe as scripts/screen_crypto_2yr.py).
SYMBOLS = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "XLM", "NEAR", "HBAR", "FET", "SUI", "ALGO", "BCH", "DOT", "SHIB", "ATOM",
    "ICP", "FIL", "UNI", "OP", "ARB", "ETC", "AAVE", "APT",
]
WIN_START = datetime(2024, 6, 15, tzinfo=timezone.utc)
WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
N_SEGMENTS = 6                       # OOS calendar slices for robustness
START_CASH = Decimal("25000")


class P(BaseModel):
    model_config = {"extra": "forbid"}
    rsi_period: int = Field(default=14, ge=2, le=100)
    sma_period: int = Field(default=200, ge=20, le=1000)
    entry_long: float = Field(default=42.0, ge=1, le=50)
    exit_long: float = Field(default=60.0, ge=50, le=99)
    take_profit_pct: float = Field(default=0.04, ge=0, le=0.5)
    stop_loss_pct: float = Field(default=0.06, ge=0, le=0.5)
    position_pct: float = Field(default=90.0, gt=0, le=100)


class RegimeReversion(Strategy[P]):
    """Proven RSI-MR + SMA200 long-only. Entry sizing scaled by an injected,
    forward-filled gross_exposure timeline (set via attach_exposure())."""

    PARAMS_MODEL = P

    def on_init(self) -> None:
        self.symbol = self.symbols[0]
        self.state["entry_px"] = None
        # Injected by attach_exposure(); default = always full (== base strategy).
        if not hasattr(self, "_dec_ts_ns"):
            self._dec_ts_ns = np.array([], dtype=np.int64)
            self._dec_ex = np.array([], dtype=float)

    def attach_exposure(self, decisions) -> None:
        ts_ns, ex = [], []
        for d in decisions:
            ts_ns.append(pd.Timestamp(d.ts).value)
            ex.append(float(d.gross_exposure))
        order = np.argsort(ts_ns)
        self._dec_ts_ns = np.array(ts_ns, dtype=np.int64)[order]
        self._dec_ex = np.array(ex, dtype=float)[order]

    def _exposure_now(self, ts) -> float:
        if self._dec_ts_ns.size == 0:
            return 1.0
        t = pd.Timestamp(ts).value
        idx = int(np.searchsorted(self._dec_ts_ns, t, side="left")) - 1  # strictly < t
        return float(self._dec_ex[idx]) if idx >= 0 else 1.0

    def on_bar(self, ctx: BarContext) -> None:
        sym = self.symbol
        p = self.params
        price = ctx.close(sym)
        rsi = ctx.rsi(sym, p.rsi_period)
        sma = ctx.sma(sym, p.sma_period)
        if price is None or rsi is None or sma is None or float(price) <= 0:
            return
        r, px, sv = float(rsi), float(price), float(sma)
        pos = ctx.position(sym)
        if pos == 0:
            expo = self._exposure_now(ctx.ts)
            qty = expo * (p.position_pct / 100.0) * ctx.cash / price
            if qty <= 0:
                return
            if r < p.entry_long and px > sv:
                ctx.signal("regime_long", value=r, symbol=sym)
                ctx.submit_buy_market(sym, qty)
                self.state["entry_px"] = px
        elif pos > 0:
            ep = self.state["entry_px"]
            tp_hit = p.take_profit_pct > 0 and ep is not None and px >= ep * (1 + p.take_profit_pct)
            sl_hit = p.stop_loss_pct > 0 and ep is not None and px <= ep * (1 - p.stop_loss_pct)
            if r > p.exit_long or tp_hit or sl_hit:
                ctx.signal("regime_long_exit", value=r, symbol=sym)
                ctx.submit_sell_market(sym, pos)
                self.state["entry_px"] = None


def _equity_series(result) -> pd.Series:
    pts = result.equity_curve
    if not pts:
        return pd.Series(dtype=float)
    idx = [pd.Timestamp(p.ts) for p in pts]
    val = [float(p.total_equity) for p in pts]
    return pd.Series(val, index=idx).sort_index()


def _seg_return(eq: pd.Series, s: pd.Timestamp, e: pd.Timestamp) -> float | None:
    if eq.empty:
        return None
    a = eq.asof(s)
    b = eq.asof(e)
    if a is None or b is None or a != a or b != b or a <= 0:
        return None
    return (b / a - 1) * 100


def _metrics(result) -> dict:
    a = compute_analytics(result)
    return {
        "ret": a.total_return_pct, "sharpe": a.sharpe_ratio,
        "dd": a.max_drawdown_pct, "trades": a.num_closed_trades,
        "win": a.win_rate_pct, "pf": a.profit_factor,
    }


def _run(symbol_full: str, bars: dict, cfg: BacktestConfig, decisions=None) -> dict:
    strat = RegimeReversion([symbol_full], P())
    if decisions is not None:
        strat.attach_exposure(decisions)
    res = run_backtest(strat, bars, cfg)
    m = _metrics(res)
    m["_eq"] = _equity_series(res)
    return m


def _fixed_decisions(df, expo: float):
    """One synthetic decision at window start -> constant exposure everywhere.
    The null hypothesis: does the LLM beat just running at its own AVERAGE leverage?"""
    return [RegimeDecision(ts=df.index[0].to_pydatetime(), gross_exposure=expo,
                           regime="fixed", notes="", source="fixed")]


def _seg_wins(eq_a, eq_b, seg_edges):
    """Count calendar segments where book B beats book A (B minus A > 0)."""
    wins = total = 0
    deltas = []
    for k in range(len(seg_edges) - 1):
        a = _seg_return(eq_a, seg_edges[k], seg_edges[k + 1])
        b = _seg_return(eq_b, seg_edges[k], seg_edges[k + 1])
        if a is None or b is None:
            continue
        total += 1
        wins += b > a
        deltas.append(b - a)
    return wins, total, deltas


async def main():
    mock = os.environ.get("META_MOCK") == "1"
    mode = "MOCK-RULE" if mock else f"LLM ({os.environ.get('META_MODEL', 'claude-sonnet-4-6')})"
    print(f"=== META-LAYER A/B  ({mode})  {WIN_START.date()}..{WIN_END.date()}  "
          f"{len(SYMBOLS)} symbols ===", flush=True)
    print("arms: CONTROL=exposure 1.0 | FIXED=exposure pinned at LLM mean (null) | "
          "META=LLM regime\n", flush=True)
    engine = get_engine()
    cfg = BacktestConfig(starting_cash=START_CASH, fee_rate_bps=5, slippage_bps=3)
    seg_edges = pd.date_range(WIN_START, WIN_END, periods=N_SEGMENTS + 1, tz="UTC")

    out = open(f"/app/logs/meta_ab{'_mock' if mock else ''}.jsonl", "w")
    rows = []
    hdr = (f"{'sym':6}{'exp':>5}  {'ctrl%':>8}{'fixed%':>8}{'meta%':>8} | "
           f"{'m-ctrl':>7}{'m-fix':>7} | {'ddC':>6}{'ddM':>6} | {'shC':>5}{'shM':>5} | "
           f"{'vsC':>5}{'vsF':>5}")
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)
    for base in SYMBOLS:
        symf = f"{base}-USDT@BINANCEUS"
        df = await load_bars(engine, symf, "1h", start=WIN_START, end=WIN_END)
        if df is None or df.empty:
            print(f"{base:6} no bars", flush=True)
            continue
        bars = {symf: df}
        decisions = compute_regime_timeline(df, symbol_tag=base, cadence_bars=24)
        ex_vals = np.array([d.gross_exposure for d in decisions]) if decisions else np.array([1.0])
        ex_mean = float(ex_vals.mean())

        ctrl = _run(symf, bars, cfg)                                       # 1.0
        fixed = _run(symf, bars, cfg, decisions=_fixed_decisions(df, ex_mean))  # null
        treat = _run(symf, bars, cfg, decisions=decisions)                 # LLM

        wC, nC, dC = _seg_wins(ctrl["_eq"], treat["_eq"], seg_edges)   # meta vs control
        wF, nF, dF = _seg_wins(fixed["_eq"], treat["_eq"], seg_edges)  # meta vs fixed (null)

        print(f"{base:6}{ex_mean:>5.2f}  {ctrl['ret']:>+8.1f}{fixed['ret']:>+8.1f}"
              f"{treat['ret']:>+8.1f} | {treat['ret']-ctrl['ret']:>+7.1f}"
              f"{treat['ret']-fixed['ret']:>+7.1f} | {ctrl['dd']:>6.0f}{treat['dd']:>6.0f} | "
              f"{(ctrl['sharpe'] or 0):>5.2f}{(treat['sharpe'] or 0):>5.2f} | "
              f"{wC:>2}/{nC:<2}{wF:>2}/{nF:<2}", flush=True)

        rec = {"symbol": base, "mode": mode, "exposure_mean": ex_mean,
               "control": {k: v for k, v in ctrl.items() if k != "_eq"},
               "fixed": {k: v for k, v in fixed.items() if k != "_eq"},
               "meta": {k: v for k, v in treat.items() if k != "_eq"},
               "meta_vs_control_segwins": [wC, nC], "meta_vs_fixed_segwins": [wF, nF],
               "seg_delta_vs_control": dC, "seg_delta_vs_fixed": dF}
        out.write(json.dumps(rec, default=float) + "\n"); out.flush()
        rows.append(rec)

    out.close()
    await engine.dispose()

    # -------- universe aggregate --------
    n = len(rows)
    if not n:
        print("no rows", flush=True); return
    meanret = lambda arm: sum(r[arm]["ret"] for r in rows) / n
    meandd = lambda arm: sum(r[arm]["dd"] for r in rows) / n
    meansh = lambda arm: sum((r[arm]["sharpe"] or 0) for r in rows) / n
    beat_ctrl = sum(r["meta"]["ret"] > r["control"]["ret"] for r in rows)
    beat_fix = sum(r["meta"]["ret"] > r["fixed"]["ret"] for r in rows)
    sw_c = (sum(r["meta_vs_control_segwins"][0] for r in rows),
            sum(r["meta_vs_control_segwins"][1] for r in rows))
    sw_f = (sum(r["meta_vs_fixed_segwins"][0] for r in rows),
            sum(r["meta_vs_fixed_segwins"][1] for r in rows))

    print(f"\n========== UNIVERSE VERDICT  (n={n}) ==========", flush=True)
    print(f"  mean return:  CONTROL {meanret('control'):+.1f}%   "
          f"FIXED {meanret('fixed'):+.1f}%   META {meanret('meta'):+.1f}%", flush=True)
    print(f"  mean maxDD:   CONTROL {meandd('control'):.1f}%    META {meandd('meta'):.1f}%",
          flush=True)
    print(f"  mean sharpe:  CONTROL {meansh('control'):+.2f}     FIXED {meansh('fixed'):+.2f}"
          f"     META {meansh('meta'):+.2f}", flush=True)
    print(f"\n  META beats CONTROL (1.0x):  {beat_ctrl}/{n} symbols, "
          f"{sw_c[0]}/{sw_c[1]} OOS segments", flush=True)
    print(f"  META beats FIXED   (null):  {beat_fix}/{n} symbols, "
          f"{sw_f[0]}/{sw_f[1]} OOS segments   <-- THE key test", flush=True)
    print("\n  GO only if META clearly beats the FIXED null (else the LLM is just "
          "de-leveraging and a constant multiplier does the same for free).", flush=True)
    print(f"\n-> logs/meta_ab{'_mock' if mock else ''}.jsonl", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
