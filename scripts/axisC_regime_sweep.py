"""Axis C: does an explicit ADX regime switch beat a fixed de-leverage null?

RegimeSwitch (ADX gates trend-vs-MR) vs DeleverNull (MR only, fixed exposure),
long-only, on LINK/BTC/BNB 1h, REAL engine at realistic cost (fee10/slip5 = 30bps),
2yr both-halves. The switch must beat its null AND be both-halves-positive (then DSR)."""
from __future__ import annotations
import json
import pandas as pd
from packages.backtest.engine import run_backtest
from packages.backtest.types import BacktestConfig
from packages.backtest.analytics import compute_analytics
from packages.strategy.loader import load_user_strategy_class

CSV = "/app/logs/xr_1h.csv"
SRC = open("/app/logs/strat_regime_switch.py").read()
SYMS = [("LINK", 53, "LINK-USDT@BINANCEUS")]   # focus: the one candidate with a pulse
ADX_THRS = [22.0, 30.0]          # detector param = trials
NULL_POS = [45.0]                # de-leverage lever
CFG = BacktestConfig(fee_rate_bps=10, slippage_bps=5, allow_short=False)  # long-only

raw = pd.read_csv(CSV); raw["bucket"] = pd.to_datetime(raw["bucket"], utc=True)
for c in ("open", "high", "low", "close", "volume"):
    raw[c] = raw[c].astype(float)

def dffor(iid):
    s = raw[raw.instrument_id == iid].sort_values("bucket").set_index("bucket")
    s = s[["open", "high", "low", "close", "volume"]]
    s = s[~s.index.duplicated(keep="first")]
    return s[(s.index >= "2024-01-01") & (s.index <= "2026-06-22 23:59:59+00:00")]

Switch = load_user_strategy_class(SRC, "RegimeSwitch")
Null = load_user_strategy_class(SRC, "DeleverNull")

def run(cls, canon, sub, **params):
    s = cls(symbols=[canon], params=cls.PARAMS_MODEL(**params))
    r = run_backtest(s, {s.symbols[0]: sub}, CFG)
    an = compute_analytics(r)
    return dict(ret=float(r.total_return_pct), sharpe=an.sharpe_ratio or 0.0,
                maxdd=an.max_drawdown_pct, trades=an.num_closed_trades)

print(f"{'sym':5}{'variant':18}{'window':7}{'ret%':>9}{'sharpe':>8}{'maxDD%':>8}{'trd':>5}", flush=True)
out = open("/app/logs/axisC_regime.jsonl", "w")
for sym, iid, canon in SYMS:
    d = dffor(iid); mid = len(d) // 2
    W = [("full", d), ("H1", d.iloc[:mid]), ("H2", d.iloc[mid:])]
    variants = [(f"switch_adx{int(t)}", Switch, dict(adx_thr=t)) for t in ADX_THRS]
    variants += [(f"null_pos{int(pp)}", Null, dict(position_pct=pp)) for pp in NULL_POS]
    for vname, cls, params in variants:
        rec_w = {}
        for wname, sub in W:
            m = run(cls, canon, sub, **params)
            rec = dict(sym=sym, variant=vname, window=wname, **m)
            rec_w[wname] = m
            out.write(json.dumps(rec) + "\n"); out.flush()
            print(f"{sym:5}{vname:18}{wname:7}{m['ret']:>+8.1f}%{m['sharpe']:>8.2f}{m['maxdd']:>+7.1f}%{m['trades']:>5}", flush=True)
        h1, h2 = rec_w["H1"]["ret"], rec_w["H2"]["ret"]
        print(f"  -> {sym} {vname}: both-halves {'PASS' if (h1>0 and h2>0) else 'FAIL'} (H1 {h1:+.1f}% / H2 {h2:+.1f}%)", flush=True)
    print(flush=True)
out.close()
print("done -> logs/axisC_regime.jsonl", flush=True)
