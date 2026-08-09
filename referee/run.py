"""End-to-end gauntlet run. Emits the survivor list and the failure clusters.

  python -m referee.run            # full run + noise battery
Stops and screams if the noise battery starts passing.
"""
from __future__ import annotations
import json, sys, time, tempfile
from collections import Counter, defaultdict
import numpy as np
from referee import corpus as corpus_mod, verdict as V, noise

SEED = "referee-v1-2026-06-24"


def annualize(sr_bar, tf):
    bpy = {"1h": 365*24, "4h": 365*6}[tf]
    return sr_bar * np.sqrt(bpy)


def run_real():
    t0 = time.time()
    prog = V.program_trial_count()
    C = corpus_mod.build_corpus(S_blocks=16)
    res = V.evaluate(C, prog["program_trials"])
    res["build_secs"] = round(time.time() - t0, 1)
    res["program"] = prog
    return res


def run_noise():
    with tempfile.TemporaryDirectory() as td:
        noise.make_null_logs(td, seed=7)
        prog = 1200  # pool size; n_trials for the null = its own size
        C = corpus_mod.build_corpus(S_blocks=16, logs=td)
        return V.evaluate(C, prog)


def main():
    res = run_real()
    rows = res["rows"]
    survivors = [r for r in rows if r["deploy"]]
    pbo = res["pbo"]

    print("=" * 78)
    print("REFEREE GAUNTLET — full corpus, net of 30bps round-trip (fee10+slip5)")
    print("=" * 78)
    print(f"scored pool          : {res['n_pool']} configs (matrix50 archetypes x 12 syms x 2 tf)")
    print(f"honest n_trials      : {res['n_trials_program']}  (full program trial count, fed to DSR)")
    print(f"  -> trial families  : " + ", ".join(f"{k.split('.')[0]}={v}"
          for k, v in list(res['program']['families'].items())))
    print(f"empirical V          : {res['V']:.3e}   SR0(deflation bar) = {res['sr0_bar']:.4f}/bar")
    print(f"corpus PBO (CSCV)    : {pbo['pbo']:.3f} over {pbo['n_splits']} splits, S={pbo['S']}"
          f"   (>= {V.PBO_BAR} => overfit search)")
    print(f"build time           : {res['build_secs']}s")

    # ---------- NOISE BATTERY ----------
    nz = run_noise()
    nz_surv = [r for r in nz["rows"] if r["deploy"]]
    print("\n--- NOISE BATTERY (block-bootstrapped null prices) ---")
    print(f"null survivors       : {len(nz_surv)}   null PBO = {nz['pbo']['pbo']:.3f}")
    if len(nz_surv) > 0:
        print("\n*** STOP: gauntlet PASSED configs on NOISE. Engine is broken. Verdicts void. ***")
        for r in nz_surv[:10]:
            print("   NULL-SURVIVOR", r["id"], f"DSR={r['dsr']:.3f}")
        sys.exit(2)
    print("battery GREEN: noise produces zero survivors.")

    # ---------- 1. SURVIVOR LIST ----------
    print("\n" + "=" * 78)
    print(f"1. SURVIVOR LIST  ({len(survivors)} clear DEPLOY)")
    print("=" * 78)
    if not survivors:
        print(">>> EMPTY. ZERO configs clear DEPLOY.")
        print(">>> Out of the entire corpus, NOTHING is statistically real net of cost")
        print(f">>> under honest deflation (n_trials={res['n_trials_program']}). You have no edge here,")
        print(">>> and that is the true answer — not a coin flip dressed as a strategy.")
    else:
        survivors.sort(key=lambda r: -r["dsr"])
        print(f"{'rank':>4} {'config':34}{'DSR':>6}{'PBO':>6}{'netSh':>7}{'MinTRL/T':>11}  regime")
        for k, r in enumerate(survivors, 1):
            regime = "both+" if r["both_halves"] else "1-regime"
            print(f"{k:>4} {r['id']:34}{r['dsr']:>6.3f}{pbo['pbo']:>6.2f}"
                  f"{annualize(r['sr_bar_full'], r['tf']):>7.2f}"
                  f"{r['min_trl']/r['T']:>10.2f}x  {regime}")

    # ---------- 1b. NEAR-SURVIVOR DIAGNOSTICS ----------
    # the only real candidates are configs that clear regime-robustness + net+.
    cand = [r for r in rows if r["both_halves"] and r["sr_bar_full"] > 0]
    cand.sort(key=lambda r: -annualize(r["sr_bar_full"], r["tf"]))
    from referee import stats as _st
    print("\n--- closest-to-real (both-halves+ AND net-Sharpe+): "
          f"{len(cand)} configs, ALL killed by deflation ---")
    print(f"{'config':34}{'netShAnn':>9}{'DSR_N1':>8}{'DSR_N3400':>10}{'MinTRL/T':>10}")
    for r in cand[:10]:
        dsr_n1 = _st.deflated_sharpe(r["sr_bar_full"],
                                     _st.expected_max_sharpe(1, res["V"]),
                                     r["T"], r["skew"], r["kurt"])
        print(f"{r['id']:34}{annualize(r['sr_bar_full'], r['tf']):>9.2f}"
              f"{dsr_n1:>8.3f}{r['dsr']:>10.3f}{r['min_trl']/r['T']:>9.1f}x")
    if cand:
        best = cand[0]
        bycoin = Counter(r["base"] for r in cand)
        print(f"best candidate {best['id']}: ann net Sharpe "
              f"{annualize(best['sr_bar_full'], best['tf']):.2f}, "
              f"DSR even at N=1 is {_st.deflated_sharpe(best['sr_bar_full'], _st.expected_max_sharpe(1, res['V']), best['T'], best['skew'], best['kurt']):.3f}")
        print(f"candidate symbol spread: {dict(bycoin.most_common())}")

    # ---------- 2. KILL CLUSTERS ----------
    print("\n" + "=" * 78)
    print("2. KILL LIST — clustered by dominant failure mode")
    print("=" * 78)
    clusters = defaultdict(list)
    for r in rows:
        clusters[V.classify_failure(r)].append(r)
    order = ["SURVIVOR", "deflation_collapse", "single_regime", "gross_pos_net_neg",
             "no_signal", "both_halves_negative", "no_edge"]
    explain = {
        "deflation_collapse": "looked real (both halves +, net Sharpe +) but DSR<=0.95 once "
                              "the full trial count is charged. The mirage is selection bias.",
        "single_regime":      "positive in one half, negative in the other. 2024-trend or "
                              "2025-spike that does not repeat. Not robust.",
        "gross_pos_net_neg":  "had a real gross signal but the 30bps cost wall turned it "
                              "net-negative. Edge < cost.",
        "no_signal":          "negative even BEFORE costs. No signal to begin with.",
        "both_halves_negative":"net-negative in both halves. Dead.",
        "no_edge":            "Sharpe <= 0; never significant at any track length.",
    }
    for mode in order:
        if mode == "SURVIVOR" or not clusters[mode]:
            continue
        grp = clusters[mode]
        # which archetypes dominate this failure -> "same mistake N times?"
        by_strat = Counter(r["strat"].split("_", 1)[0] for r in grp)
        top = ", ".join(f"#{s}x{n}" for s, n in by_strat.most_common(6))
        print(f"\n[{mode}]  {len(grp)}/{len(rows)} configs")
        print(f"   {explain[mode]}")
        print(f"   dominant archetypes: {top}")
    # the meta-lesson: how concentrated are the failures?
    nonsurv = [r for r in rows if not r["deploy"]]
    modes = Counter(V.classify_failure(r) for r in nonsurv)
    biggest = modes.most_common(1)[0]
    print("\n" + "-" * 78)
    print(f"PATTERN: {biggest[1]}/{len(nonsurv)} failures ({100*biggest[1]/len(nonsurv):.0f}%) "
          f"are the SAME mode '{biggest[0]}'.")
    print("=> One mistake repeated, not 100 different ones." if biggest[1] > len(nonsurv)*0.4
          else "=> Failures are spread across modes.")

    # persist raw verdict rows (signed) for the report stage
    out = {"meta": {k: res[k] for k in ("n_pool", "n_trials_program", "V", "sr0_bar", "dsr_bar")},
           "pbo": pbo, "noise_survivors": len(nz_surv),
           "survivors": [V.sign_record(r, SEED) for r in survivors],
           "rows": rows}
    with open("/app/logs/referee_verdict.json", "w") as f:
        json.dump(out, f, default=float)
    print(f"\nwrote /app/logs/referee_verdict.json ({len(rows)} verdict records)")


if __name__ == "__main__":
    main()
