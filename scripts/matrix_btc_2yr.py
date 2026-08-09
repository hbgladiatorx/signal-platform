"""BTC-only 50-strategy matrix over the FULL 2-year window, with built-in OOS.

Reuses the exact 50 platform-implementable archetypes from matrix_strats.py (14
indicator families — every one expressible as a platform strategy graph: SMA/EMA
cross, price-vs-MA, MACD, ROC, RSI, Stoch, Bollinger, VWAP, Donchian, ATR bands,
and 7 multi-indicator combos). Long-flat, spot-realistic.

What's different from the prior matrix (and WHY): the old run used 1-3 month
SAME-REGIME windows on 5m/15m — the exact mistake the Donchian retraction taught
us. This runs the FULL 2yr (2024-06-15..2026-06-15, multi-regime) on BTC at the
two timeframes the O(n^2) engine can actually handle over 2yr — 1h (~17.5k bars)
and 4h (~4.4k bars) — and scores each strategy on:
  - full-window return / sharpe / maxDD / profit-factor / trades-per-day
  - OOS robustness: return in each of 4 DISJOINT calendar segments (a real
    edge is positive in most regimes, not one lucky stretch)
A strategy only "survives" if it's net-of-cost positive full-window AND positive
in >=3/4 segments AND pf>=1.1 AND trades enough to be real.

Realistic cost: 10bps fee + 5bps slippage = 30bps round trip.

  docker compose run --rm -d -w /app --name btc_matrix -e PYTHONPATH=/app \
    -v /home/signal/app/scripts:/app/scripts \
    -v /home/signal/app/logs:/app/logs \
    backtest_worker python scripts/matrix_btc_2yr.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.instruments import load_instrument_meta
from packages.data.db import get_engine
from packages.livetrade.bars import load_bars

import matrix_strats as ms  # the 50 archetypes + FuncStrat + _P

BTC = "BTC-USDT@BINANCEUS"
WIN_START = datetime(2024, 6, 15, tzinfo=timezone.utc)
WIN_END = datetime(2026, 6, 15, tzinfo=timezone.utc)
TFS = ["1h", "4h"]
BARS_PER_DAY = {"1h": 24, "4h": 6}
N_SEG = 4
OUT = "/app/logs/matrix_btc_2yr.jsonl"


def _eq_series(result) -> pd.Series:
    pts = result.equity_curve
    if not pts:
        return pd.Series(dtype=float)
    return pd.Series([float(p.total_equity) for p in pts],
                     index=[pd.Timestamp(p.ts) for p in pts]).sort_index()


def _seg_ret(eq: pd.Series, s, e) -> float | None:
    if eq.empty:
        return None
    a, b = eq.asof(s), eq.asof(e)
    if a is None or b is None or a != a or b != b or a <= 0:
        return None
    return (b / a - 1) * 100


def _survivor(r: dict) -> bool:
    st = r.get("stats")
    if not st:
        return False
    return (st["total_return_pct"] > 0 and (st["profit_factor"] or 0) >= 1.1
            and st["num_trades"] >= 20 and r["seg_pos"] >= 3)


async def main() -> None:
    engine = get_engine()
    out = open(OUT, "w")
    all_rows = []
    for tf in TFS:
        t0 = time.time()
        df = await load_bars(engine, BTC, tf, start=WIN_START, end=WIN_END)
        meta = await load_instrument_meta(engine, [BTC])
        n = 0 if df is None else len(df)
        if df is None or df.empty:
            print(f"[{tf}] no bars", file=sys.stderr, flush=True)
            continue
        bh = (float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100
        days = n / BARS_PER_DAY[tf]
        seg_edges = pd.date_range(WIN_START, WIN_END, periods=N_SEG + 1, tz="UTC")
        print(f"[{tf}] {n} bars ({days:.0f}d), BTC B&H {bh:+.1f}% -- running 50 strats",
              file=sys.stderr, flush=True)

        rows = []
        for i, (name, family, (en, ex)) in enumerate(ms.SPECS, 1):
            rec = {"tf": tf, "strategy": name, "family": family, "bh_pct": bh}
            ts = time.time()
            try:
                strat = ms.FuncStrat(symbols=[BTC], params=ms._P())
                strat._enter, strat._exit = en, ex
                cfg = BacktestConfig(starting_cash=Decimal("10000"),
                                     fee_rate_bps=10, slippage_bps=5, instrument_meta=meta)
                result = run_backtest(strat, {BTC: df}, cfg)
                a = compute_analytics(result)
                eq = _eq_series(result)
                segs = [_seg_ret(eq, seg_edges[k], seg_edges[k + 1]) for k in range(N_SEG)]
                rec["segs"] = segs
                rec["seg_pos"] = sum(1 for x in segs if x is not None and x > 0)
                rec["stats"] = {
                    "total_return_pct": a.total_return_pct, "sharpe": a.sharpe_ratio,
                    "max_drawdown_pct": a.max_drawdown_pct, "num_trades": a.num_closed_trades,
                    "tpd": round(a.num_closed_trades / days, 2),
                    "win_rate_pct": a.win_rate_pct, "profit_factor": a.profit_factor,
                }
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
                rec["seg_pos"] = 0
            rec["secs"] = round(time.time() - ts, 1)
            out.write(json.dumps(rec, default=float) + "\n"); out.flush()
            rows.append(rec)
            r = rec.get("stats", {}).get("total_return_pct")
            tag = "ERR" if "error" in rec else f"{r:+.1f}% seg+{rec['seg_pos']}/4"
            print(f"  [{tf} {i}/50] {name}: {tag} ({rec['secs']}s)", file=sys.stderr, flush=True)
        all_rows.extend(rows)
        print(f"[{tf}] done in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)

    out.close()
    await engine.dispose()

    # ---------------- ranked report ----------------
    for tf in TFS:
        rows = [r for r in all_rows if r["tf"] == tf and "stats" in r]
        if not rows:
            continue
        rows.sort(key=lambda r: (_survivor(r), r["stats"]["total_return_pct"]), reverse=True)
        bh = rows[0]["bh_pct"]
        print(f"\n===== BTC {tf}  2yr  (B&H {bh:+.1f}%) =====")
        print(f"{'strategy':22}{'family':11}{'ret%':>8}{'pf':>6}{'sh':>6}{'dd%':>7}"
              f"{'trd':>5}{'/day':>6}{'OOS segs (4 disjoint)':>26} ok")
        for r in rows:
            st = r["stats"]
            segs = " ".join(f"{x:+.0f}" if x is not None else "  na" for x in r["segs"])
            print(f"{r['strategy'][:22]:22}{r['family'][:11]:11}"
                  f"{st['total_return_pct']:>+8.1f}{(st['profit_factor'] or 0):>6.2f}"
                  f"{(st['sharpe'] or 0):>6.2f}{st['max_drawdown_pct']:>7.0f}"
                  f"{st['num_trades']:>5}{st['tpd']:>6.2f}  [{segs:>20}] "
                  f"{'Y' if _survivor(r) else '.'}")

    survivors = [r for r in all_rows if _survivor(r)]
    print(f"\n========== SURVIVORS (net+, pf>=1.1, >=20 trd, >=3/4 OOS segs): "
          f"{len(survivors)} / {len([r for r in all_rows if 'stats' in r])} ==========")
    for r in sorted(survivors, key=lambda r: r["stats"]["total_return_pct"], reverse=True):
        st = r["stats"]
        beats_bh = st["total_return_pct"] > r["bh_pct"]
        print(f"  {r['tf']:3} {r['strategy']:22} {st['total_return_pct']:+.1f}% "
              f"pf={st['profit_factor']:.2f} sh={(st['sharpe'] or 0):.2f} "
              f"tpd={st['tpd']} segs+{r['seg_pos']}/4  {'BEATS B&H' if beats_bh else 'lags B&H'}")
    print(f"\n-> {OUT}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
