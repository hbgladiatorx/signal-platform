"""Compute cross-sectional reversal autocorr from a pre-dumped CSV (no DB load).

CSV cols: instrument_id, bucket, close  (12 symbols, 15m, 2024-01-01..2026-06-22).
Per half, measure:
  spearman : cross-sectional rank corr(trailing k-bar return, forward h-bar return)
             >0 momentum (reversal LOSES) | <0 reversion (reversal WINS gross)
  LS spread: mean fwd-return(losers we buy) - (winners we short), bps/hold
"""
import json
import numpy as np
import pandas as pd

ID2BASE = {15:"ADA",44:"AVAX",12:"BCH",14:"BNB",1:"BTC",20:"DOGE",
           46:"DOT",2:"ETH",53:"LINK",13:"LTC",6:"SOL",11:"XRP"}

df = pd.read_csv("/app/logs/xr_close.csv")
df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
wide = df.pivot_table(index="bucket", columns="instrument_id", values="close")
wide = wide.sort_index().dropna(how="any")          # common aligned bars
C = wide.to_numpy(float)
T, S = C.shape
print(f"aligned {S} symbols x {T} bars ({T/(24*4)/365.25:.2f}y)\n", flush=True)


def rankrow(a):
    out = np.full(a.shape, np.nan); v = ~np.isnan(a)
    out[v] = pd.Series(a[v]).rank().to_numpy()
    return out


def spearman(x, y):
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < 4: return np.nan
    rx = rankrow(np.where(m, x, np.nan))[m]; ry = rankrow(np.where(m, y, np.nan))[m]
    rx = rx - rx.mean(); ry = ry - ry.mean()
    d = np.sqrt((rx @ rx) * (ry @ ry))
    return float(rx @ ry / d) if d > 0 else np.nan


def analyze(C, k, h, n_long, a, b):
    cc = C[a:b]; Tn = cc.shape[0]
    trail = np.full_like(cc, np.nan); trail[k:] = cc[k:] / cc[:-k] - 1.0
    fwd = np.full_like(cc, np.nan); fwd[:-h] = cc[h:] / cc[:-h] - 1.0
    corrs, spreads = [], []
    for t in range(k, Tn - h, h):
        x, y = trail[t], fwd[t]
        c = spearman(x, y)
        if not np.isnan(c): corrs.append(c)
        m = ~np.isnan(x) & ~np.isnan(y)
        if m.sum() >= 2 * n_long + 2:
            order = np.argsort(np.where(m, x, np.inf)); nv = int(m.sum())
            losers = order[:n_long]; winners = order[nv - n_long:nv]
            spreads.append(float(np.nanmean(y[losers]) - np.nanmean(y[winners])))
    return (float(np.nanmean(corrs)) if corrs else np.nan,
            float(np.nanmean(spreads)) * 1e4 if spreads else np.nan, len(corrs))


mid = T // 2
slabs = [("full", 0, T), ("H1-2024", 0, mid), ("H2-25/26", mid, T)]
print("corr<0 reversion(reversal WINS) | corr>0 momentum(reversal LOSES)")
print("spread = fwd-ret(losers we buy) - (winners we short), bps/hold; ~30bps round-trip cost\n")
print(f"{'k':>4}{'h':>4}  {'slab':10}{'spearman':>10}{'LS spread bps':>15}{'n':>7}", flush=True)
out = open("/app/logs/vec_xreversal_autocorr.jsonl", "w")
for (k, h) in [(48, 8), (96, 8), (48, 16), (96, 16)]:
    for tag, a, b in slabs:
        corr, spread, n = analyze(C, k, h, 3, a, b)
        print(f"{k:>4}{h:>4}  {tag:10}{corr:>+10.4f}{spread:>+15.2f}{n:>7}", flush=True)
        out.write(json.dumps(dict(k=k, h=h, slab=tag, spearman=corr,
                                  ls_spread_bps=spread, n=n)) + "\n")
    print(flush=True)
out.close()
print("-> logs/vec_xreversal_autocorr.jsonl", flush=True)
