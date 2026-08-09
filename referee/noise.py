"""Synthetic noise battery. Builds null price data with NO persistent edge by
block-bootstrapping each instrument's bar-to-bar returns, then rebuilds an
OHLCV table with the SAME schema so the real archetypes run unchanged.

The gauntlet must return ZERO survivors on this. If it doesn't, the engine is
finding edges in noise and the whole run is void.
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
from referee.corpus import TF_LIST
from scripts.matrix50_robust import ID2BASE


def make_null_logs(out_dir: str, seed: int = 0, block: int = 24,
                   src="/app/logs"):
    """Write null xr_<tf>.csv files to out_dir, schema-identical to source."""
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    for tf in TF_LIST:
        src_df = pd.read_csv(f"{src}/xr_{tf}.csv")
        src_df["bucket"] = pd.to_datetime(src_df["bucket"], utc=True)
        rows = []
        for iid in ID2BASE:
            d = src_df[src_df.instrument_id == iid].sort_values("bucket")
            if len(d) < 500:
                continue
            c = d["close"].to_numpy(dtype=float)
            ret = np.diff(c) / c[:-1]
            # DEMEAN: remove unconditional drift so long-biased configs have no
            # edge in the null. Otherwise the bootstrap preserves the crypto
            # uptrend and "always long" persists IS->OOS (false structure).
            ret = ret - np.nanmean(ret)
            T = len(ret)
            # block-bootstrap returns: sample contiguous blocks with replacement
            idx = []
            while len(idx) < T:
                s = int(rng.integers(0, max(T - block, 1)))
                idx.extend(range(s, min(s + block, T)))
            idx = np.array(idx[:T])
            bret = ret[idx]
            price = np.empty(T + 1)
            price[0] = c[0]
            price[1:] = c[0] * np.cumprod(1 + bret)
            close = price
            openp = np.empty_like(close); openp[0] = close[0]; openp[1:] = close[:-1]
            hi = np.maximum(openp, close) * (1 + np.abs(rng.normal(0, 0.0005, close.size)))
            lo = np.minimum(openp, close) * (1 - np.abs(rng.normal(0, 0.0005, close.size)))
            vol = rng.permutation(d["volume"].to_numpy(dtype=float))[:close.size]
            buckets = d["bucket"].to_numpy()[:close.size]
            for k in range(close.size):
                rows.append((iid, buckets[k], openp[k], hi[k], lo[k], close[k], vol[k]))
        out = pd.DataFrame(rows, columns=["instrument_id", "bucket", "open",
                                          "high", "low", "close", "volume"])
        out.to_csv(f"{out_dir}/xr_{tf}.csv", index=False)
    return out_dir
