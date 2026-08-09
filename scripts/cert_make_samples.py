#!/usr/bin/env python3
"""Generate SYNTHETIC external strategy submissions for an end-to-end cert demo.

These are impersonal outside evidence — NOT our own corpus. Seeded so the demo is
reproducible. Three cases exercise the integrity surface:

  A. honest_edge_equity.csv   — a genuinely strong daily equity curve (ann Sharpe
                                ~1.7), submitted as an EQUITY CURVE. Declared
                                trials=1 (honest single hypothesis). Should PASS
                                at n_trials=1 and FAIL when re-graded at trials=500
                                (same data, dishonest trial hiding) — the trial-
                                count integrity feature, visible.
  B. snooped_returns.csv      — the SAME edge but submitted as a RETURNS series; we
                                grade it at a declared trials=500 to show deflation
                                killing a 1-of-many lucky pick.
  C. lookahead_equity.csv     — a too-good, near-monotone equity curve (ann Sharpe
                                ~40, almost no losing days) -> must come back
                                UNVERIFIABLE on the look-ahead integrity tell.

Writes to app/logs/cert_samples/.
"""
import os
import numpy as np
import pandas as pd

OUT = "/app/logs/cert_samples"
os.makedirs(OUT, exist_ok=True)
START = "2021-06-01"


def daily_dates(n):
    # business-day calendar so the integrity pass sees realistic weekday gaps
    return pd.bdate_range(START, periods=n, tz="UTC")


def make_edge_returns(n, ann_sharpe, seed, ann_vol=0.16):
    rng = np.random.default_rng(seed)
    ppy = 252.0
    per_vol = ann_vol / np.sqrt(ppy)
    per_mean = ann_sharpe / np.sqrt(ppy) * per_vol
    # Student-t innovations for realistic fat tails (noise battery must still pass it)
    z = rng.standard_t(df=6, size=n) / np.sqrt(6 / 4)
    return per_mean + per_vol * z


def main():
    # ---- A: honest strong edge, as an equity curve ----
    n = 880
    dates = daily_dates(n)
    r = make_edge_returns(n, ann_sharpe=1.7, seed=20240601)
    equity = 100000.0 * np.cumprod(1 + r)
    pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "equity": np.round(equity, 2)}) \
        .to_csv(f"{OUT}/honest_edge_equity.csv", index=False)

    # ---- B: same family of edge, as a returns series (graded at high trials) ----
    pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "return": np.round(r, 6)}) \
        .to_csv(f"{OUT}/snooped_returns.csv", index=False)

    # ---- C: look-ahead tell: near-monotone equity, almost no losing days ----
    rng = np.random.default_rng(7)
    r_la = np.abs(rng.normal(0.004, 0.0008, n))   # almost always positive, tiny vol
    eq_la = 100000.0 * np.cumprod(1 + r_la)
    pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "equity": np.round(eq_la, 2)}) \
        .to_csv(f"{OUT}/lookahead_equity.csv", index=False)

    for f in ("honest_edge_equity.csv", "snooped_returns.csv", "lookahead_equity.csv"):
        print("wrote", f"{OUT}/{f}")


if __name__ == "__main__":
    main()
