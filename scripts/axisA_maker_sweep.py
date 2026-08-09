"""Axis A: does realistic MAKER execution revive LINK L/S?

Runs the pure-maker LINK strategy on the REAL engine over the 2yr both-halves split,
sweeping the engine's maker frictions from optimistic to pessimistic. Reports
ret/sharpe/maxDD/trades/fill-rate and the both-halves verdict. Taker baseline (from
verify_costs) for reference: 2yr full @30bps = -27.8% (FAIL both halves)."""
from __future__ import annotations
import json
import pandas as pd
from packages.backtest.engine import run_backtest
from packages.backtest.types import BacktestConfig
from packages.backtest.analytics import compute_analytics
from packages.strategy.loader import load_user_strategy_class

CSV = "/app/logs/xr_1h.csv"
SRC = open("/app/logs/strat_link_maker.py").read()
CANON = "LINK-USDT@BINANCEUS"
IID = 53

# (label, maker_fee_bps, through_margin_bps, adverse_selection_bps)
CONFIGS = [
    ("M1_optimistic", 2, 0, 0),
    ("M2_moderate", 5, 10, 3),
    ("M3_realistic", 5, 20, 5),
    ("M4_pessimistic", 8, 40, 10),
]
OFFSET_BPS = 5.0

raw = pd.read_csv(CSV); raw["bucket"] = pd.to_datetime(raw["bucket"], utc=True)
for c in ("open", "high", "low", "close", "volume"):
    raw[c] = raw[c].astype(float)
d = raw[raw.instrument_id == IID].sort_values("bucket").set_index("bucket")
d = d[["open", "high", "low", "close", "volume"]]
d = d[~d.index.duplicated(keep="first")]
d = d[(d.index >= "2024-01-01") & (d.index <= "2026-06-22 23:59:59+00:00")]
mid = len(d) // 2
WINDOWS = [("full", d), ("H1", d.iloc[:mid]), ("H2", d.iloc[mid:])]

cls = load_user_strategy_class(SRC, "MakerRegime")

print(f"{'config':16}{'window':7}{'ret%':>9}{'sharpe':>8}{'maxDD%':>8}{'trd':>5}{'fill%':>7}", flush=True)
out = open("/app/logs/axisA_maker.jsonl", "w")
for lbl, fee, thru, adv in CONFIGS:
    cfg = BacktestConfig(maker_fee_bps=fee, fill_through_margin_bps=thru,
                         adverse_selection_bps=adv, slippage_bps=5, fee_rate_bps=10)
    res_by_w = {}
    for wname, sub in WINDOWS:
        strat = cls(symbols=[CANON], params=cls.PARAMS_MODEL(offset_bps=OFFSET_BPS))
        res = run_backtest(strat, {strat.symbols[0]: sub}, cfg)
        an = compute_analytics(res)
        fillrate = (100.0 * res.num_trades / res.orders_submitted) if res.orders_submitted else 0.0
        rec = dict(config=lbl, fee=fee, thru=thru, adv=adv, window=wname,
                   ret=float(res.total_return_pct), sharpe=an.sharpe_ratio or 0.0,
                   maxdd=an.max_drawdown_pct, trades=an.num_closed_trades,
                   fills=res.num_trades, orders=res.orders_submitted, fill_rate=fillrate)
        res_by_w[wname] = rec
        out.write(json.dumps(rec) + "\n"); out.flush()
        print(f"{lbl:16}{wname:7}{rec['ret']:>+8.1f}%{rec['sharpe']:>8.2f}{rec['maxdd']:>+7.1f}%"
              f"{rec['trades']:>5}{fillrate:>6.0f}%", flush=True)
    h1, h2 = res_by_w["H1"]["ret"], res_by_w["H2"]["ret"]
    print(f"  -> {lbl}: both-halves {'PASS' if (h1>0 and h2>0) else 'FAIL'} (H1 {h1:+.1f}% / H2 {h2:+.1f}%)\n", flush=True)
out.close()
print("done -> logs/axisA_maker.jsonl", flush=True)
