"""Regenerate per-config return SERIES from the vectorized corpus.

The stored *.jsonl rows hold only summary metrics; CSCV/PBO needs the per-bar
return series. We import the EXACT archetype + cost logic that produced the
corpus (scripts.matrix50_robust) so there is zero drift, and re-emit the per-bar
net-of-cost return series for every (timeframe, symbol, archetype) config.

Cost basis: matrix50_robust COST_SIDE = (10+5)/1e4 per side = 30bps round-trip,
identical to the event-driven BacktestConfig default. Every number here is NET.

Look-ahead controls applied to the REAL series (not only in tests):
  - signals act next bar (eff = pos.shift(1)) — inherited from simulate().
  - purge+embargo: the first EMBARGO bars of every CSCV calendar block are
    dropped, so an IS block cannot leak indicator lookback into the adjacent
    OOS block.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from scripts.matrix50_robust import S as build_signals, COST_SIDE, ID2BASE, BARS_PER_YEAR

TF_LIST = ["1h", "4h"]
# embargo (bars) >= deepest indicator lookback per tf (sma200 etc.) so no block
# boundary leaks. Generous on purpose; CSCV blocks are large.
EMBARGO = {"1h": 200, "4h": 60}


def _sr_series(pos: pd.Series, close: pd.Series) -> pd.Series:
    """Per-bar net return series — byte-identical formula to matrix50.simulate()."""
    pos = pos.fillna(0).clip(0, 1)
    ret = close.pct_change().fillna(0)
    eff = pos.shift(1).fillna(0)
    cost = eff.diff().abs().fillna(eff.abs()) * COST_SIDE
    return eff * ret - cost


def build_corpus(tf_list=TF_LIST, S_blocks: int = 16, logs="/app/logs"):
    """Returns a dict with aligned CSCV block stats + per-config DSR inputs.

    keys:
      ids       : list[str]  config id "tf:base:strat"
      meta      : list[dict] per-config {tf,base,strat,T,ret_full,ret_h1,ret_h2,
                  trades,expo,sharpe_ann_full, sr_bar_full, skew, kurt}
      block_sum_r, block_sum_r2, block_n : (C, S) arrays, embargoed
      sr_bar    : (C,) per-bar Sharpe (full window) for empirical V
    """
    # global calendar range across everything we load (for common blocks)
    frames = {}
    tmin = tmax = None
    for tf in tf_list:
        df0 = pd.read_csv(f"{logs}/xr_{tf}.csv")
        df0["bucket"] = pd.to_datetime(df0["bucket"], utc=True)
        frames[tf] = df0
        lo, hi = df0["bucket"].min(), df0["bucket"].max()
        tmin = lo if tmin is None else min(tmin, lo)
        tmax = hi if tmax is None else max(tmax, hi)
    span = (tmax - tmin).total_seconds()

    ids, meta = [], []
    bsr, bsr2, bn, srbar = [], [], [], []

    for tf in tf_list:
        df0 = frames[tf]
        emb = EMBARGO[tf]
        for iid, base in ID2BASE.items():
            d = df0[df0.instrument_id == iid].sort_values("bucket").set_index("bucket")
            d = d[["open", "high", "low", "close", "volume"]].astype(float)
            if len(d) < 500:
                continue
            T = len(d)
            mid = T // 2
            sigs = build_signals(d)
            # block index per bar on the GLOBAL calendar
            secs = (d.index - tmin).total_seconds().to_numpy()
            blk = np.clip((secs / span * S_blocks).astype(int), 0, S_blocks - 1)
            for name, pos in sigs.items():
                sr = _sr_series(pos, d.close).to_numpy()
                # gross (pre-cost) per-bar return, to separate cost-bled deaths
                # from no-signal deaths in the failure clustering.
                eff_s = pos.fillna(0).clip(0, 1).shift(1).fillna(0)
                gross = (eff_s.to_numpy() * d.close.pct_change().fillna(0).to_numpy())
                # per-window summary (matches stored corpus semantics)
                def _ret(a, b):
                    return float((np.prod(1 + sr[a:b]) - 1) * 100)
                gross_full = float((np.prod(1 + gross) - 1) * 100)
                eff = pos.shift(1).fillna(0).to_numpy()
                trades = int((np.abs(np.diff(eff, prepend=0)) > 0).sum())
                sd = sr.std(ddof=1)
                sh_ann = float(sr.mean()/sd*np.sqrt(BARS_PER_YEAR[tf])) if sd > 0 else 0.0
                sr_bar = float(sr.mean()/sd) if sd > 0 else 0.0
                m = (sr - sr.mean())
                s2 = sr.std(ddof=0)
                skew = float(np.mean((m/s2)**3)) if s2 > 0 else 0.0
                kurt = float(np.mean((m/s2)**4)) if s2 > 0 else 3.0
                # embargoed block accumulation. blk is non-decreasing (time-sorted),
                # so within-block position is vectorizable: idx since the block changed.
                sumr = np.zeros(S_blocks); sumr2 = np.zeros(S_blocks); nn = np.zeros(S_blocks)
                idx = np.arange(T)
                change = np.empty(T, dtype=bool); change[0] = True
                change[1:] = blk[1:] != blk[:-1]
                start = np.maximum.accumulate(np.where(change, idx, 0))
                order = idx - start
                keep = order >= emb
                for b in range(S_blocks):
                    msk = keep & (blk == b)
                    if msk.any():
                        seg = sr[msk]
                        sumr[b] = seg.sum(); sumr2[b] = (seg**2).sum(); nn[b] = seg.size
                ids.append(f"{tf}:{base}:{name}")
                meta.append(dict(tf=tf, base=base, strat=name, T=T,
                                 ret_full=_ret(0, T), ret_h1=_ret(0, mid), ret_h2=_ret(mid, T),
                                 ret_gross_full=gross_full,
                                 trades=trades, expo=float(eff.mean()),
                                 sharpe_ann_full=sh_ann, sr_bar_full=sr_bar,
                                 skew=skew, kurt=kurt))
                bsr.append(sumr); bsr2.append(sumr2); bn.append(nn); srbar.append(sr_bar)

    return dict(ids=ids, meta=meta,
                block_sum_r=np.array(bsr), block_sum_r2=np.array(bsr2),
                block_n=np.array(bn), sr_bar=np.array(srbar),
                S=S_blocks, t_min=str(tmin), t_max=str(tmax))
