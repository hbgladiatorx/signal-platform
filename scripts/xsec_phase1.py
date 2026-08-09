#!/usr/bin/env python3
"""Cross-sectional top-k momentum, long-only spot, run through app/referee/.

Executes EXACTLY the locked pre-registration (app/logs/xsec_prereg.json, schema
xsec.prereg/1). Asserts the signature before running. Each rebalance ranks the
universe by trailing L-day return and holds the top-k equal-weight; the series
fed to the referee is EXCESS over the equal-weight basket, deflated against the
full cumulative n_trials=3496. Reuses the UNMODIFIED referee.stats /
referee.verdict / referee.noise so the math is byte-identical to the matrix50
corpus and funding runs. Writes a signed verdict and prints it.

Run (ephemeral container with live code bind-mounted):
  docker run --rm -v /home/signal/app:/app -w /app -e PYTHONPATH=/app \
      app-backtest_worker python scripts/xsec_phase1.py
"""
from __future__ import annotations
import json, hashlib, sys, time
from collections import Counter, defaultdict
from itertools import combinations
import numpy as np
import pandas as pd

sys.path.insert(0, "/app")
from referee import stats, verdict as V, noise

PREREG_PATH = "/app/logs/xsec_prereg.json"
OUT_PATH = "/app/logs/xsec_verdict_signed.json"
XR_1H = "/app/logs/xr_1h.csv"
COST_SIDE = 0.0015               # 30bps round-trip (locked, identical to corpus & funding)
BARS_PER_YEAR_D = 365            # daily bars

SYM2ID = {"ADA": 15, "AVAX": 44, "BCH": 12, "BNB": 14, "BTC": 1, "DOGE": 20,
          "DOT": 46, "ETH": 2, "LINK": 53, "LTC": 13, "SOL": 6, "XRP": 11}


# ---------------------------------------------------------------- prereg load
def load_and_verify_prereg():
    p = json.load(open(PREREG_PATH))
    seed = p["seed"]; stored = p.get("_sig")
    recomputed = hashlib.sha256(
        seed.encode() + json.dumps({k: v for k, v in p.items() if k != "_sig"},
                                   sort_keys=True, default=float).encode()).hexdigest()
    if p.get("schema") != "xsec.prereg/1":
        print(f"*** HALT: schema is {p.get('schema')}, expected xsec.prereg/1"); sys.exit(3)
    if stored != recomputed:
        print("*** HALT: pre-registration signature MISMATCH — file edited after signing.")
        print(f"    stored     {stored}\n    recomputed {recomputed}"); sys.exit(3)
    print(f"prereg OK  schema={p['schema']}  seed={seed}  sig={stored[:16]}...  (verified)")
    return p, seed


# ---------------------------------------------------------------- data build
def build_daily_closes(xr_path, symbols):
    """1h OHLCV -> daily close per symbol, inner-joined to a common daily calendar."""
    df = pd.read_csv(xr_path)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    cols = {}
    for sym in symbols:
        iid = SYM2ID[sym]
        d = df[df.instrument_id == iid].sort_values("bucket").set_index("bucket")
        if len(d) < 500:
            continue
        cols[sym] = d["close"].resample("1D", label="right", closed="left").last()
    closes = pd.DataFrame(cols).dropna(how="any")     # balanced cross-section every day
    return closes


# ---------------------------------------------------- cross-sectional strategy
def xsec_excess(closes: pd.DataFrame, L: int, k: int, reb: int, warmup: int):
    """Long-only top-k momentum excess over the equal-weight basket.

    Returns dict with the post-warmup excess series + raw diagnostics. No look-
    ahead: weights decided at close t act on day t+1 (W_eff = W_held.shift(1))."""
    dates = closes.index
    n = len(dates)
    syms = list(closes.columns)
    R = closes.pct_change()                            # daily simple returns
    W = pd.DataFrame(np.nan, index=dates, columns=syms)
    n_reb = 0
    for ti in range(L, n):
        if (ti - L) % reb != 0:                        # weekly grid anchored at first rankable day
            continue
        score = (closes.iloc[ti] / closes.iloc[ti - L] - 1.0).dropna()
        winners = list(score.sort_values(ascending=False).index[:k])
        w = pd.Series(0.0, index=syms)
        w[winners] = 1.0 / k
        W.iloc[ti] = w.values
        n_reb += 1
    W = W.ffill().fillna(0.0)                           # hold between rebalances; flat before first
    W_eff = W.shift(1).fillna(0.0)                      # act next day (no look-ahead)
    port_ret = (W_eff * R.fillna(0.0)).sum(axis=1)
    turnover = W_eff.diff().abs().sum(axis=1).fillna(W_eff.iloc[0].abs().sum())
    cost = turnover * COST_SIDE
    bench = R.mean(axis=1)                              # equal-weight basket, costless
    excess = (port_ret - cost - bench)

    sl = slice(warmup, n)
    ex = excess.iloc[sl]
    idx = ex.index
    trades = int((turnover.iloc[sl] > 1e-12).sum())
    return dict(
        excess=ex, index=idx,
        port_total=float((1 + port_ret.iloc[sl]).prod() - 1) * 100,
        bench_total=float((1 + bench.iloc[sl]).prod() - 1) * 100,
        net_total=float((1 + (port_ret - cost).iloc[sl]).prod() - 1) * 100,
        turnover_sum=float(turnover.iloc[sl].sum()), trades=trades, n_reb=n_reb,
        gross_excess=(port_ret - bench).iloc[sl],
        exposure=float((W_eff.iloc[sl].sum(axis=1)).mean()))


def config_meta(strat, ex: np.ndarray, gross: np.ndarray, expo, trades, years):
    T = len(ex); mid = T // 2
    srb = stats.sharpe_per_bar(ex)
    sk, ku = stats.moments(ex)
    reg = {int(y): float(ex[years == y].sum()) for y in np.unique(years)}
    return dict(tf="1D", base="XSEC", strat=strat, T=T,
                ret_full=float(ex.sum()), ret_h1=float(ex[:mid].sum()), ret_h2=float(ex[mid:].sum()),
                ret_gross_full=float(gross.sum()), trades=int(trades), expo=float(expo),
                sharpe_ann_full=float(srb * np.sqrt(BARS_PER_YEAR_D)), sr_bar_full=float(srb),
                skew=float(sk), kurt=float(ku), regime=reg)


def block_stats(ex: np.ndarray, blk: np.ndarray, S: int, embargo: int):
    T = len(ex); idx = np.arange(T)
    change = np.empty(T, bool); change[0] = True; change[1:] = blk[1:] != blk[:-1]
    start = np.maximum.accumulate(np.where(change, idx, 0))
    keep = (idx - start) >= embargo
    sr = np.zeros(S); sr2 = np.zeros(S); nn = np.zeros(S)
    for b in range(S):
        msk = keep & (blk == b)
        if msk.any():
            seg = ex[msk]; sr[b] = seg.sum(); sr2[b] = (seg**2).sum(); nn[b] = seg.size
    return sr, sr2, nn


def build_corpus(closes, prereg, S=16, embargo=14):
    g = prereg["signal"]["grid"]
    L_set, K_set, reb = g["lookback_days"], g["top_k"], g["rebalance_days"]
    warmup = prereg["signal"]["warmup_days"]
    ids, meta, bsr, bsr2, bn, srbar, raws = [], [], [], [], [], [], {}
    for L in L_set:
        for k in K_set:
            r = xsec_excess(closes, L, k, reb, warmup)
            idx = r["index"]; years = idx.year.to_numpy(); exn = r["excess"].to_numpy()
            strat = f"mom_L{L}_k{k}"
            m = config_meta(strat, exn, r["gross_excess"].to_numpy(), r["exposure"],
                            r["trades"], years)
            m["raw"] = {kk: r[kk] for kk in ("port_total", "bench_total", "net_total",
                                             "turnover_sum", "n_reb")}
            secs = (idx - idx[0]).total_seconds().to_numpy()
            span = (idx[-1] - idx[0]).total_seconds()
            blk = np.clip((secs / span * S).astype(int), 0, S - 1)
            sr, sr2, nn = block_stats(exn, blk, S, embargo)
            ids.append(f"1D:XSEC:{strat}")
            meta.append(m); bsr.append(sr); bsr2.append(sr2); bn.append(nn)
            srbar.append(m["sr_bar_full"]); raws[strat] = r
    return dict(ids=ids, meta=meta, block_sum_r=np.array(bsr), block_sum_r2=np.array(bsr2),
                block_n=np.array(bn), sr_bar=np.array(srbar), S=S,
                t_min=str(closes.index[0]), t_max=str(closes.index[-1])), raws


# ----------------------------------------------------- single-name dependence
def single_name_dependence(closes, L, k, reb, warmup):
    """Leave-one-out and leave-two-out over the RANKING+BENCHMARK pool.
    Returns the worst-case total excess after removing 1 and 2 names."""
    syms = list(closes.columns)
    loo = {}
    for s in syms:
        sub = closes.drop(columns=[s])
        loo[s] = float(xsec_excess(sub, L, min(k, sub.shape[1]), reb, warmup)["excess"].sum())
    worst1_name = min(loo, key=loo.get); worst1 = loo[worst1_name]
    worst2, worst2_pair = np.inf, None
    for a, b in combinations(syms, 2):
        sub = closes.drop(columns=[a, b])
        tot = float(xsec_excess(sub, L, min(k, sub.shape[1]), reb, warmup)["excess"].sum())
        if tot < worst2:
            worst2, worst2_pair = tot, (a, b)
    return {"loo_worst": worst1, "loo_worst_name": worst1_name, "loo_all": loo,
            "lto_worst": float(worst2), "lto_worst_pair": list(worst2_pair),
            "single_name_dependent": bool(worst1 <= 0 or worst2 <= 0)}


# ------------------------------------------------------------------- noise
def run_noise_battery(prereg, seed=7):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        noise.make_null_logs(td, seed=seed)
        closes = build_daily_closes(f"{td}/xr_1h.csv", list(SYM2ID))
        C, _ = build_corpus(closes, prereg)
        res = V.evaluate(C, len(C["ids"]))            # noise n_trials = its own pool size
        return [r for r in res["rows"] if r["deploy"]], res["pbo"]["pbo"], len(C["ids"])


# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    prereg, seed = load_and_verify_prereg()
    N_TRIALS = prereg["n_trials"]["cumulative_n_trials"]
    assert N_TRIALS == 3496, "locked cumulative n_trials must be 3496"
    reb = prereg["signal"]["grid"]["rebalance_days"]
    warmup = prereg["signal"]["warmup_days"]

    closes = build_daily_closes(XR_1H, list(SYM2ID))
    print(f"daily cross-section: {closes.shape[1]} symbols x {closes.shape[0]} days "
          f"({closes.index[0].date()} -> {closes.index[-1].date()}); post-warmup T="
          f"{closes.shape[0]-warmup}")

    C, raws = build_corpus(closes, prereg)
    res = V.evaluate(C, N_TRIALS)
    rows, pbo = res["rows"], res["pbo"]

    # regime + single-name robustness on any DEPLOY
    for r in rows:
        reg = r["regime"]
        yrs = {y: v for y, v in reg.items() if y in (2024, 2025)}
        r["both_calendar_pos"] = (len(yrs) >= 2) and all(v > 0 for v in yrs.values())
    deploy_rows = [r for r in rows if r["deploy"]]
    survivors, conditional = [], []
    for r in deploy_rows:
        L = int(r["strat"].split("_L")[1].split("_k")[0]); k = int(r["strat"].split("_k")[1])
        snd = single_name_dependence(closes, L, k, reb, warmup)
        r["single_name"] = snd
        r["robust"] = bool(r["both_calendar_pos"] and not snd["single_name_dependent"])
        (survivors if r["robust"] else conditional).append(r)

    nz_surv, nz_pbo, nz_pool = run_noise_battery(prereg)

    if nz_surv:
        call = "VOID_ENGINE_BROKEN"
    elif survivors:
        call = "DEPLOY"
    elif conditional:
        call = "HOLD_CONDITIONAL"
    else:
        call = "REJECT"

    # =================== PRINT ===================
    line = "=" * 82
    print("\n" + line)
    print("CROSS-SECTIONAL TOP-K MOMENTUM — long-only spot, vs EQUAL-WEIGHT BASKET")
    print(line)
    print(f"universe         : {closes.shape[1]} majors  {', '.join(closes.columns)}")
    print(f"scored pool      : {len(rows)} configs (3 lookbacks x 2 top-k, weekly rebalance)")
    print(f"benchmark        : equal-weight basket (excess series); positive => beats holding all")
    print(f"cost             : {COST_SIDE*1e4:.0f}bps/side = 30bps round-trip (locked)")
    print(f"honest n_trials  : {res['n_trials_program']}  (prior program 3490 + xsec 6)")
    print(f"empirical V      : {res['V']:.3e}   SR0(deflation bar) = {res['sr0_bar']:.4f}/bar")
    print(f"corpus PBO (CSCV): {pbo['pbo']:.3f} over {pbo['n_splits']} splits, S={pbo['S']}  "
          f"(>= {V.PBO_BAR} => overfit)")
    print(f"build time       : {round(time.time()-t0,1)}s")

    print("\n--- per-config detail (excess over equal-weight basket) ---")
    print(f"{'config':20}{'exSh':>7}{'DSR':>7}{'bothH':>7}{'2024':>8}{'2025':>8}{'2026':>8}"
          f"{'stratTot%':>10}{'baskTot%':>10}{'trd':>5}")
    for r in sorted(rows, key=lambda x: -x["sr_bar_full"]):
        rg = r["regime"]
        print(f"{r['strat']:20}{r['sharpe_ann_full']:>7.2f}{r['dsr']:>7.3f}"
              f"{('Y' if r['both_halves'] else '.'):>7}"
              f"{rg.get(2024,0):>8.3f}{rg.get(2025,0):>8.3f}{rg.get(2026,0):>8.3f}"
              f"{r['raw']['port_total']:>10.1f}{r['raw']['bench_total']:>10.1f}{r['trades']:>5}")

    print("\n--- NOISE BATTERY (block-bootstrapped, demeaned null prices) ---")
    print(f"null survivors   : {len(nz_surv)}   null PBO = {nz_pbo:.3f}   null pool = {nz_pool}")
    if nz_surv:
        print("\n*** HALT: gauntlet PASSED configs on NOISE. Engine broken. Verdict VOID. ***")
        for r in nz_surv[:10]:
            print("   NULL-SURVIVOR", r["id"], f"DSR={r['dsr']:.3f}")
    else:
        print("battery GREEN: cross-sectional momentum finds zero edge in noise.")

    print("\n" + line)
    print(f"SURVIVORS (robust DEPLOY): {len(survivors)}   |   CONDITIONAL: {len(conditional)}")
    print(line)
    if survivors:
        for r in sorted(survivors, key=lambda x: -x["dsr"]):
            print(f"  DEPLOY {r['id']:24} DSR={r['dsr']:.3f} exSh={r['sharpe_ann_full']:.2f} "
                  f"MinTRL/T={r['min_trl']/r['T']:.2f}x  LOOworst={r['single_name']['loo_worst']:.4f}")
    else:
        print(">>> EMPTY. Zero configs beat the equal-weight basket on a deflation- and PBO-aware basis.")
    if conditional:
        print(f"\n--- CONDITIONAL (clears DSR vs basket but single-regime or single-name) ---")
        for r in sorted(conditional, key=lambda x: -x["dsr"]):
            why = []
            if not r["both_calendar_pos"]: why.append("single-regime")
            if r["single_name"]["single_name_dependent"]:
                why.append(f"single-name(drop {r['single_name']['loo_worst_name']}"
                           f"->{r['single_name']['loo_worst']:.3f})")
            print(f"   {r['id']:24} DSR={r['dsr']:.3f} exSh={r['sharpe_ann_full']:.2f} [{','.join(why)}]")

    # closest-to-real diagnostics
    cand = [r for r in rows if r["both_halves"] and r["sr_bar_full"] > 0]
    cand.sort(key=lambda r: -r["sharpe_ann_full"])
    print(f"\n--- closest-to-real (beat basket both halves AND excess-Sharpe>0): {len(cand)} configs ---")
    if cand:
        print(f"{'config':20}{'exShAnn':>9}{'DSR_N1':>8}{'DSR_3496':>10}{'MinTRL/T':>10}")
        for r in cand[:12]:
            dsr_n1 = stats.deflated_sharpe(r["sr_bar_full"], stats.expected_max_sharpe(1, res["V"]),
                                           r["T"], r["skew"], r["kurt"])
            trl = r["min_trl"] / r["T"] if np.isfinite(r["min_trl"]) else float("inf")
            print(f"{r['strat']:20}{r['sharpe_ann_full']:>9.2f}{dsr_n1:>8.3f}{r['dsr']:>10.3f}{trl:>9.1f}x")
    else:
        print("   none — no config beats the basket in both halves with positive excess Sharpe.")

    # failure clusters
    print("\n" + line); print("FAILURE CLUSTERS"); print(line)
    clusters = defaultdict(list)
    for r in rows:
        clusters[V.classify_failure(r)].append(r)
    for mode in ["SURVIVOR", "deflation_collapse", "single_regime", "gross_pos_net_neg",
                 "no_signal", "both_halves_negative", "no_edge"]:
        gset = clusters.get(mode, [])
        if mode == "SURVIVOR" or not gset:
            continue
        print(f"[{mode:22}] {len(gset):>2}/{len(rows)}   configs: " +
              ", ".join(r["strat"] for r in gset))

    print("\n" + line); print(f"FINAL CALL: {call}"); print(line)
    print({"DEPLOY": "A robust cross-sectional edge beats the equal-weight basket under honest deflation.",
           "HOLD_CONDITIONAL": "Edge(s) clear DSR vs basket but are single-regime / single-name — human call, NOT auto-deploy.",
           "REJECT": "No config beats the equal-weight basket under honest deflation + PBO. The cross-sectional axis is closed with a clean, rigorous null.",
           "VOID_ENGINE_BROKEN": "Noise battery passed configs — engine void, verdict cannot be trusted."}[call])

    # =================== SIGN + WRITE ===================
    def clean(r):
        out = {}
        for k2, v in r.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                out[k2] = None
            else:
                out[k2] = v
        return out
    out = {
        "schema": "referee.verdict/1", "phase": "xsec.phase1", "seed": seed,
        "prereg_sig": prereg["_sig"], "as_of": prereg["as_of"],
        "universe": list(closes.columns), "benchmark": "equal_weight_basket (excess series)",
        "cost_model": {"side_bps": COST_SIDE * 1e4, "round_trip_bps": 30},
        "n_trials": {"prior_program": 3490, "xsec": 6, "cumulative": N_TRIALS},
        "corpus": {"n_pool": res["n_pool"], "V": res["V"], "sr0_bar": res["sr0_bar"],
                   "dsr_bar": res["dsr_bar"], "t_min": C["t_min"], "t_max": C["t_max"]},
        "pbo_cscv": {"pbo": pbo["pbo"], "n_splits": pbo["n_splits"], "S": pbo["S"], "bar": V.PBO_BAR},
        "noise_battery": {"null_survivors": len(nz_surv), "null_pbo": nz_pbo,
                          "null_pool": nz_pool, "status": "GREEN" if not nz_surv else "BROKEN"},
        "n_survivors": len(survivors),
        "survivors": [V.sign_record(clean(r), seed) for r in survivors],
        "conditional": [clean(r) for r in conditional],
        "failure_clusters": {m: len(g) for m, g in clusters.items()},
        "rows": [clean(r) for r in rows], "verdict": call,
    }
    signed = V.sign_record(out, seed)
    with open(OUT_PATH, "w") as f:
        json.dump(signed, f, default=float, indent=2)
    print(f"\nwrote {OUT_PATH}  ({len(rows)} verdict records)  sig {signed['_sig'][:16]}...")


if __name__ == "__main__":
    main()
