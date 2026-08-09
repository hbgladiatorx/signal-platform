#!/usr/bin/env python3
"""Phase 1 — funding-gated CONTRARIAN long/flat spot, run through app/referee/.

Executes EXACTLY the locked v2 pre-registration (app/logs/funding_prereg.json,
schema funding.prereg/2). Asserts the signature before running. Feeds the referee
the excess-over-buy-and-hold series so every verdict is measured against holding
the asset, deflated against the full cumulative n_trials=3490. Reuses the
UNMODIFIED referee.stats / referee.verdict / referee.noise so the math is byte-
identical to the matrix50 corpus run. Writes a signed verdict and prints it.

Run (ephemeral container with live code bind-mounted):
  docker run --rm -v /home/signal/app:/app -w /app -e PYTHONPATH=/app \
      app-backtest_worker python scripts/funding_phase1.py
"""
from __future__ import annotations
import json, hashlib, sys, time
from collections import Counter, defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, "/app")
from referee import stats, verdict as V, noise
from scripts.matrix50_robust import COST_SIDE  # 0.0015 == 30bps round-trip (locked)

PREREG_PATH = "/app/logs/funding_prereg.json"
OUT_PATH = "/app/logs/funding_verdict_signed.json"
XR_1H = "/app/logs/xr_1h.csv"
PERP = "/app/logs/perp"
BARS_PER_YEAR_8H = 365 * 3  # 3 settlements/day

# instrument_id -> base, for the 9-symbol universe (BNB excluded a priori)
SYM2ID = {"BTC": 1, "ETH": 2, "SOL": 6, "XRP": 11, "ADA": 15,
          "DOGE": 20, "LINK": 53, "AVAX": 44, "LTC": 13}


# ---------------------------------------------------------------- prereg load
def load_and_verify_prereg():
    p = json.load(open(PREREG_PATH))
    seed = p["seed"]
    stored = p.get("_sig")
    recomputed = hashlib.sha256(
        seed.encode() + json.dumps({k: v for k, v in p.items() if k != "_sig"},
                                   sort_keys=True, default=float).encode()).hexdigest()
    if p.get("schema") != "funding.prereg/2":
        print(f"*** HALT: schema is {p.get('schema')}, expected funding.prereg/2"); sys.exit(3)
    if stored != recomputed:
        print("*** HALT: pre-registration signature MISMATCH — file edited after signing.")
        print(f"    stored     {stored}\n    recomputed {recomputed}"); sys.exit(3)
    print(f"prereg OK  schema={p['schema']}  seed={seed}  sig={stored[:16]}...  (signature verified)")
    return p, seed


# ---------------------------------------------------------------- data build
def build_8h_bars(xr_path):
    """Resample 1h OHLCV -> 8h aligned to the 00/08/16 UTC funding clock.
    Returns {sym: DataFrame[open,high,low,close,volume] indexed by 8h right-edge ts}."""
    df = pd.read_csv(xr_path)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    out = {}
    for sym, iid in SYM2ID.items():
        d = df[df.instrument_id == iid].sort_values("bucket").set_index("bucket")
        if len(d) < 500:
            continue
        b = d.resample("8h", label="right", closed="left").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum")).dropna(subset=["close"])
        out[sym] = b
    return out


def load_funding(sym):
    """funding settled at ts (00/08/16 UTC). Floor ms jitter to the exact 8h boundary."""
    f = pd.read_csv(f"{PERP}/{sym}_funding_full.csv")
    ts = pd.to_datetime(f["ts_ms"], unit="ms", utc=True).dt.floor("8h")
    return pd.Series(f["funding"].to_numpy(float), index=ts).groupby(level=0).last()


# ------------------------------------------------------- contrarian position
def contrarian_position(funding: pd.Series, L: int, margin: float, hyst: float) -> pd.Series:
    """DEFAULT LONG. exit->FLAT when funding_t >= m_t+margin (crowded); re-enter LONG
    when funding_t < m_t+margin-hyst. pos[t] decided from funding known at close t;
    acted next bar via shift(1) downstream. Returns pos in {0,1} (NaN during warmup)."""
    m = funding.rolling(L).mean()
    f = funding.to_numpy(); mm = m.to_numpy()
    pos = np.ones(len(f))                      # default LONG
    state = 1
    for t in range(len(f)):
        if not np.isnan(mm[t]):
            thr = mm[t] + margin
            if state == 1 and f[t] >= thr:
                state = 0
            elif state == 0 and f[t] < thr - hyst:
                state = 1
        pos[t] = state
    return pd.Series(pos, index=funding.index)


def excess_series(pos: pd.Series, close: pd.Series):
    """excess over buy-and-hold, per bar, net of locked cost:
         excess_t = (eff_{t}-1)*ret_t - cost_t,  eff = pos.shift(1) (default LONG).
    Returns (excess, gross_excess, eff, trades)."""
    ret = close.pct_change().fillna(0.0)
    eff = pos.shift(1).fillna(1.0)             # default LONG before first signal
    cost = eff.diff().abs().fillna(0.0) * COST_SIDE
    gross = (eff - 1.0) * ret                  # pre-cost excess
    excess = gross - cost
    trades = int((eff.diff().abs() > 0).sum())
    return excess, gross, eff, trades


# --------------------------------------------------- per-config metrics + blocks
def config_meta(base, strat, excess: np.ndarray, gross: np.ndarray, eff: np.ndarray,
                trades: int, years: np.ndarray):
    T = len(excess)
    mid = T // 2
    srb = stats.sharpe_per_bar(excess)
    sk, ku = stats.moments(excess)
    rfull, rh1, rh2 = excess.sum(), excess[:mid].sum(), excess[mid:].sum()
    # regime conditioning: excess sum per calendar year
    reg = {int(y): float(excess[years == y].sum()) for y in np.unique(years)}
    return dict(tf="8h", base=base, strat=strat, T=T,
                ret_full=float(rfull), ret_h1=float(rh1), ret_h2=float(rh2),
                ret_gross_full=float(gross.sum()), trades=trades, expo=float(eff.mean()),
                sharpe_ann_full=float(srb * np.sqrt(BARS_PER_YEAR_8H)), sr_bar_full=float(srb),
                skew=float(sk), kurt=float(ku), regime=reg)


def block_stats(excess: np.ndarray, blk: np.ndarray, S: int, embargo: int):
    """Embargoed per-block sums (drop first `embargo` bars of each block) — exact
    mirror of referee.corpus block accumulation."""
    T = len(excess)
    idx = np.arange(T)
    change = np.empty(T, bool); change[0] = True; change[1:] = blk[1:] != blk[:-1]
    start = np.maximum.accumulate(np.where(change, idx, 0))
    keep = (idx - start) >= embargo
    sumr = np.zeros(S); sumr2 = np.zeros(S); nn = np.zeros(S)
    for b in range(S):
        msk = keep & (blk == b)
        if msk.any():
            seg = excess[msk]; sumr[b] = seg.sum(); sumr2[b] = (seg**2).sum(); nn[b] = seg.size
    return sumr, sumr2, nn


# ------------------------------------------------------------------- corpus
def build_funding_corpus(bars, prereg, S=16, warmup=270, embargo=270):
    L_set = prereg["signal"]["grid"]["trailing_mean_lookback_settlements"]
    M_set = prereg["signal"]["grid"]["margin_funding_per_8h"]
    H = prereg["signal"]["grid"]["hysteresis_funding_per_8h"]

    # global 8h calendar (union across symbols) for CSCV block indexing
    all_idx = sorted(set().union(*[set(b.index) for b in bars.values()]))
    tmin, tmax = all_idx[0], all_idx[-1]
    span = (tmax - tmin).total_seconds()

    ids, meta, bsr, bsr2, bn, srbar = [], [], [], [], [], []
    per_excess = defaultdict(dict)   # (L,M) -> {sym: excess Series} for the basket

    for sym, b in bars.items():
        fund = load_funding(sym).reindex(b.index)        # funding known at each 8h close
        close = b["close"]
        for L in L_set:
            for M in M_set:
                pos = contrarian_position(fund, L, M, H)
                excess, gross, eff, trades = excess_series(pos, close)
                # uniform post-warmup window so L=21 and L=270 are comparable
                ex = excess.iloc[warmup:]
                gr = gross.iloc[warmup:]
                ef = eff.iloc[warmup:]
                idx = ex.index
                years = idx.year.to_numpy()
                exn = ex.to_numpy()
                m = config_meta(sym, f"contrarian_L{L}_m{M:g}", exn, gr.to_numpy(),
                                ef.to_numpy(), trades, years)
                secs = (idx - tmin).total_seconds().to_numpy()
                blk = np.clip((secs / span * S).astype(int), 0, S - 1)
                sr, sr2, n = block_stats(exn, blk, S, embargo)
                ids.append(f"8h:{sym}:contrarian_L{L}_m{M:g}")
                meta.append(m); bsr.append(sr); bsr2.append(sr2); bn.append(n)
                srbar.append(m["sr_bar_full"])
                per_excess[(L, M)][sym] = pd.Series(exn, index=idx)

    # ---- equal-weight BASKET: mean of the 9 per-symbol excess series per config ----
    for L in L_set:
        for M in M_set:
            d = pd.DataFrame(per_excess[(L, M)])
            basket = d.mean(axis=1).dropna()          # equal-weight, skip-missing
            idx = basket.index
            years = idx.year.to_numpy()
            exn = basket.to_numpy()
            # basket gross/eff not meaningful per-symbol; reuse excess for gross, expo=NaN
            m = config_meta("BASKET", f"contrarian_L{L}_m{M:g}", exn, exn,
                            np.full(len(exn), np.nan), -1, years)
            secs = (idx - idx[0]).total_seconds().to_numpy()
            span_b = (idx[-1] - idx[0]).total_seconds()
            blk = np.clip((secs / span_b * S).astype(int), 0, S - 1)
            sr, sr2, n = block_stats(exn, blk, S, embargo)
            ids.append(f"8h:BASKET:contrarian_L{L}_m{M:g}")
            meta.append(m); bsr.append(sr); bsr2.append(sr2); bn.append(n)
            srbar.append(m["sr_bar_full"])

    return dict(ids=ids, meta=meta, block_sum_r=np.array(bsr), block_sum_r2=np.array(bsr2),
                block_n=np.array(bn), sr_bar=np.array(srbar), S=S,
                t_min=str(tmin), t_max=str(tmax))


# ------------------------------------------------------------------- noise
def run_noise_battery(prereg, seed=7):
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        noise.make_null_logs(td, seed=seed)           # null 1h prices (demeaned bootstrap)
        bars = build_8h_bars(f"{td}/xr_1h.csv")
        C = build_funding_corpus(bars, prereg)
        res = V.evaluate(C, len(C["ids"]))            # noise n_trials = its own pool size
        surv = [r for r in res["rows"] if r["deploy"]]
        return surv, res["pbo"]["pbo"], len(C["ids"])


# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    prereg, seed = load_and_verify_prereg()
    N_TRIALS = prereg["n_trials"]["cumulative_n_trials"]          # 3490 (locked)
    assert N_TRIALS == 3490, "locked cumulative n_trials must be 3490"

    bars = build_8h_bars(XR_1H)
    print(f"loaded 8h bars: {len(bars)} symbols  " +
          ", ".join(f"{s}={len(b)}" for s, b in bars.items()))

    C = build_funding_corpus(bars, prereg)
    res = V.evaluate(C, N_TRIALS)
    rows, pbo = res["rows"], res["pbo"]

    # ---- regime + single-symbol robustness flags on any DEPLOY ----
    for r in rows:
        reg = r["regime"]
        yrs_pos = {y: v for y, v in reg.items() if y in (2024, 2025)}
        r["both_calendar_pos"] = all(v > 0 for v in yrs_pos.values()) and len(yrs_pos) >= 2
    deploy_rows = [r for r in rows if r["deploy"]]
    # a per-symbol deploy is "single-symbol" unless the SAME param deploys on >=2 symbols or basket
    def param(r): return r["strat"]
    deploy_params = Counter(param(r) for r in deploy_rows if r["base"] != "BASKET")
    for r in deploy_rows:
        multi = (r["base"] == "BASKET") or (deploy_params.get(param(r), 0) >= 2)
        r["robust"] = bool(multi and r["both_calendar_pos"])

    survivors = [r for r in deploy_rows if r.get("robust")]
    conditional = [r for r in deploy_rows if not r.get("robust")]

    # ---- noise battery ----
    nz_surv, nz_pbo, nz_pool = run_noise_battery(prereg)

    # ---- effective-trials diagnostic (raw 3490 still used for deflation) ----
    # funding sub-block: 81 per-symbol cells span only 9 distinct (L,margin) params
    eff_note = ("raw cumulative=3490 used for deflation (LOCKED). Funding sub-block: 81 "
                "per-symbol cells share 9 distinct (L,margin) params across 9 correlated "
                "symbols, so effective INDEPENDENT funding trials < 81. Deflating at the "
                "larger raw 3490 is the conservative (harder) choice; no divergence that "
                "would LOWER the bar feeds the verdict.")

    # ---- final call ----
    if nz_surv:
        call = "VOID_ENGINE_BROKEN"
    elif survivors:
        call = "DEPLOY"
    elif conditional:
        call = "HOLD_CONDITIONAL"
    else:
        call = "REJECT"

    # =================== PRINT ===================
    line = "=" * 80
    print("\n" + line)
    print("PHASE 1 VERDICT — funding-gated CONTRARIAN long/flat spot, vs BUY-AND-HOLD")
    print(line)
    print(f"universe        : 9 symbols (BNB excluded a priori)")
    print(f"scored pool      : {len(rows)} configs (81 per-symbol + 9 basket)")
    print(f"benchmark        : buy-and-hold (excess series); positive => beats holding")
    print(f"cost             : {COST_SIDE*1e4:.0f}bps/side = 30bps round-trip (locked)")
    print(f"honest n_trials  : {res['n_trials_program']}  (program 3400 + funding 90; momentum superseded=0)")
    print(f"empirical V      : {res['V']:.3e}   SR0(deflation bar) = {res['sr0_bar']:.4f}/bar")
    print(f"corpus PBO (CSCV): {pbo['pbo']:.3f} over {pbo['n_splits']} splits, S={pbo['S']}  (>= {V.PBO_BAR} => overfit)")
    print(f"build time       : {round(time.time()-t0,1)}s")

    print("\n--- NOISE BATTERY (block-bootstrapped, demeaned null prices; real funding) ---")
    print(f"null survivors   : {len(nz_surv)}   null PBO = {nz_pbo:.3f}   null pool = {nz_pool}")
    if nz_surv:
        print("\n*** HALT: gauntlet PASSED configs on NOISE. Engine broken. Verdict VOID. ***")
        for r in nz_surv[:10]:
            print("   NULL-SURVIVOR", r["id"], f"DSR={r['dsr']:.3f}")
        # still write what we have, flagged void
    else:
        print("battery GREEN: contrarian funding strategy finds zero edge in noise.")

    print("\n" + line)
    print(f"SURVIVORS (robust DEPLOY): {len(survivors)}   |   CONDITIONAL: {len(conditional)}")
    print(line)
    if survivors:
        survivors.sort(key=lambda r: -r["dsr"])
        print(f"{'config':40}{'DSR':>7}{'netShAnn':>9}{'MinTRL/T':>10}{'2024':>9}{'2025':>9}")
        for r in survivors:
            print(f"{r['id']:40}{r['dsr']:>7.3f}{r['sharpe_ann_full']:>9.2f}"
                  f"{r['min_trl']/r['T']:>9.2f}x{r['regime'].get(2024,0):>9.4f}{r['regime'].get(2025,0):>9.4f}")
    else:
        print(">>> EMPTY. Zero configs beat buy-and-hold on a deflation- and PBO-aware basis.")
    if conditional:
        print(f"\n--- CONDITIONAL (clears DSR vs B&H but single-symbol or single-regime) ---")
        for r in sorted(conditional, key=lambda r: -r["dsr"]):
            why = []
            if not r["both_calendar_pos"]: why.append("single-regime")
            if r["base"] != "BASKET" and Counter(param(x) for x in deploy_rows if x['base']!='BASKET').get(param(r),0) < 2:
                why.append("single-symbol")
            print(f"   {r['id']:40} DSR={r['dsr']:.3f} netShAnn={r['sharpe_ann_full']:.2f} [{','.join(why)}]")

    # ---- closest-to-real diagnostics (beat B&H both halves AND positive excess Sharpe) ----
    cand = [r for r in rows if r["both_halves"] and r["sr_bar_full"] > 0]
    cand.sort(key=lambda r: -r["sharpe_ann_full"])
    print(f"\n--- closest-to-real (beat B&H both halves AND excess-Sharpe>0): {len(cand)} configs ---")
    if cand:
        print(f"{'config':40}{'netShAnn':>9}{'DSR_N1':>8}{'DSR_3490':>9}{'MinTRL/T':>10}")
        for r in cand[:12]:
            dsr_n1 = stats.deflated_sharpe(r["sr_bar_full"], stats.expected_max_sharpe(1, res["V"]),
                                           r["T"], r["skew"], r["kurt"])
            print(f"{r['id']:40}{r['sharpe_ann_full']:>9.2f}{dsr_n1:>8.3f}{r['dsr']:>9.3f}{r['min_trl']/r['T']:>9.1f}x")

    # ---- failure clusters ----
    print("\n" + line); print("FAILURE CLUSTERS"); print(line)
    clusters = defaultdict(list)
    for r in rows:
        clusters[V.classify_failure(r)].append(r)
    for mode in ["SURVIVOR", "deflation_collapse", "single_regime", "gross_pos_net_neg",
                 "no_signal", "both_halves_negative", "no_edge"]:
        g = clusters.get(mode, [])
        if mode == "SURVIVOR" or not g:
            continue
        by_base = Counter(r["base"] for r in g)
        print(f"[{mode:22}] {len(g):>3}/{len(rows)}   top: " +
              ", ".join(f"{b}x{n}" for b, n in by_base.most_common(6)))

    print("\n" + line)
    print(f"FINAL CALL: {call}")
    print(line)
    print({"DEPLOY": "A robust primary edge beats buy-and-hold under honest deflation.",
           "HOLD_CONDITIONAL": "Edge(s) clear DSR vs B&H but are single-symbol/single-regime — human call, NOT auto-deploy.",
           "REJECT": "No config beats buy-and-hold under honest deflation + PBO. The funding axis is closed with a clean, rigorous null. 'Every axis tested honestly, including the structural one' is now true.",
           "VOID_ENGINE_BROKEN": "Noise battery passed configs — engine void, verdict cannot be trusted."}[call])
    print(f"\neffective-trials note: {eff_note}")

    # =================== SIGN + WRITE ===================
    def clean(r):
        return {k: (None if isinstance(v, float) and (np.isnan(v) or np.isinf(v)) else v)
                for k, v in r.items()}
    out = {
        "schema": "referee.verdict/1",
        "phase": "funding.phase1",
        "seed": seed,
        "prereg_sig": prereg["_sig"],
        "as_of": prereg["as_of"],
        "universe": list(SYM2ID),
        "bnb_excluded": True,
        "benchmark": "buy_and_hold (excess series)",
        "cost_model": {"side_bps": COST_SIDE * 1e4, "round_trip_bps": 30},
        "n_trials": {"program": 3400, "funding": 90, "cumulative": N_TRIALS,
                     "momentum_superseded": 0, "effective_note": eff_note},
        "corpus": {"n_pool": res["n_pool"], "V": res["V"], "sr0_bar": res["sr0_bar"],
                   "dsr_bar": res["dsr_bar"], "t_min": C["t_min"], "t_max": C["t_max"]},
        "pbo_cscv": {"pbo": pbo["pbo"], "n_splits": pbo["n_splits"], "S": pbo["S"], "bar": V.PBO_BAR},
        "noise_battery": {"null_survivors": len(nz_surv), "null_pbo": nz_pbo,
                          "null_pool": nz_pool,
                          "status": "GREEN" if not nz_surv else "BROKEN"},
        "n_survivors": len(survivors),
        "survivors": [V.sign_record(clean(r), seed) for r in survivors],
        "conditional": [clean(r) for r in conditional],
        "failure_clusters": {m: len(g) for m, g in clusters.items()},
        "rows": [clean(r) for r in rows],
        "verdict": call,
    }
    signed = V.sign_record({k: v for k, v in out.items()}, seed)
    with open(OUT_PATH, "w") as f:
        json.dump(signed, f, default=float, indent=2)
    print(f"\nwrote {OUT_PATH}  ({len(rows)} verdict records)  sig {signed['_sig'][:16]}...")


if __name__ == "__main__":
    main()
