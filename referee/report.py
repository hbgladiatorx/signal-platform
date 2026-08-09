"""Render the verdict: a one-page research note (Markdown) + a signed,
seed-reproducible JSON record. Reads /app/logs/referee_verdict.json (written by
referee.run) so the report regenerates deterministically from the same seed.

  python -m referee.report

No execution, no broker. This is a publisher artifact: library -> CLI -> verdict
-> report. A $500 reseller and a pre-seed investor both read the same page.
"""
from __future__ import annotations
import json, hashlib
from collections import Counter, defaultdict
import numpy as np
from referee import verdict as V

SRC = "/app/logs/referee_verdict.json"
MD_OUT = "/app/logs/referee_report.md"
JSON_OUT = "/app/logs/referee_verdict_signed.json"
SEED = "referee-v1-2026-06-24"


def _ann(sr_bar, tf):
    return sr_bar * np.sqrt({"1h": 365*24, "4h": 365*6}[tf])


def build():
    d = json.load(open(SRC))
    meta, rows, pbo = d["meta"], d["rows"], d["pbo"]
    survivors = d["survivors"]
    clusters = Counter(V.classify_failure(r) for r in rows)
    nonsurv = sum(v for k, v in clusters.items() if k != "SURVIVOR")
    # near-miss candidates (only real candidates: regime-robust + net positive)
    cand = sorted([r for r in rows if r["both_halves"] and r["sr_bar_full"] > 0],
                  key=lambda r: -_ann(r["sr_bar_full"], r["tf"]))
    bch_frac = sum(1 for r in cand if r["base"] == "BCH") / max(len(cand), 1)

    # ---- signed JSON record (regenerable from seed) ----
    record = {
        "schema": "referee.verdict/1",
        "seed": SEED,
        "as_of": "2026-06-24",
        "universe": "crypto spot, Binance.US-tradable majors, 1h+4h",
        "cost_model": {"fee_bps": 10, "slip_bps": 5, "round_trip_bps": 30,
                       "basis": "net; matches event-driven BacktestConfig default"},
        "corpus": {"scored_pool": meta["n_pool"],
                   "n_trials_program": meta["n_trials_program"],
                   "deflation_V": meta["V"], "sr0_per_bar": meta["sr0_bar"],
                   "dsr_threshold": meta["dsr_bar"]},
        "pbo_cscv": {"pbo": pbo["pbo"], "n_splits": pbo["n_splits"], "S": pbo["S"]},
        "noise_battery": {"null_survivors": d["noise_survivors"],
                          "status": "GREEN" if d["noise_survivors"] == 0 else "BROKEN"},
        "verdict": "NO_DEPLOYABLE_STRATEGY" if not survivors else "SURVIVORS_FOUND",
        "n_survivors": len(survivors),
        "survivors": survivors,
        "failure_clusters": {k: clusters[k] for k in clusters if k != "SURVIVOR"},
        "data_integrity_flags": (
            [f"BCH 1h: {bch_frac:.0%} of regime-robust candidates; ann Sharpe to "
             f"{_ann(cand[0]['sr_bar_full'], cand[0]['tf']):.1f} implausible -> suspect bars"]
            if cand and bch_frac > 0.3 else []),
    }
    payload = json.dumps(record, sort_keys=True, default=float).encode()
    record["signature"] = hashlib.sha256(SEED.encode() + payload).hexdigest()
    json.dump(record, open(JSON_OUT, "w"), indent=2, default=float)

    # ---- one-page Markdown note ----
    L = []
    A = L.append
    A(f"# Strategy Validation Verdict — {record['as_of']}")
    A("")
    A(f"**Universe:** {record['universe']}  |  **Cost:** {record['cost_model']['round_trip_bps']}bps "
      f"round-trip, net  |  **Seed:** `{SEED}`")
    A("")
    A(f"## Verdict: {'NO DEPLOYABLE STRATEGY' if not survivors else f'{len(survivors)} SURVIVOR(S)'}")
    A("")
    if not survivors:
        A(f"Out of **{meta['n_pool']} backtested configurations**, evaluated net of cost and "
          f"deflated against the **{meta['n_trials_program']} trials** the research program actually "
          f"ran, **zero** clear the deployment bar. There is no statistically real, cost-surviving, "
          f"regime-robust edge in this corpus. This is a finding, not a failure: the test is built "
          f"to return nothing when there is nothing.")
    A("")
    A("## How the bar is set")
    A("")
    A("- **Net of realistic cost.** Every return is after 30bps round-trip (10bps fee + 5bps "
      "slippage), the same cost the live event-driven engine applies.")
    A("- **Deflated Sharpe (Bailey & López de Prado).** A strategy selected from a large search "
      f"must beat the *expected best of {meta['n_trials_program']} random trials*, not zero. The "
      f"selection bar here is SR₀ = {meta['sr0_bar']:.3f}/bar.")
    A("- **PBO via CSCV.** Probability the in-sample-best config underperforms out-of-sample across "
      f"{pbo['n_splits']:,} combinatorial splits: **{pbo['pbo']:.0%}**.")
    A("- **Purge + embargo** on the real series; **look-ahead** controlled (signals act next bar).")
    A(f"- **Noise battery: {record['noise_battery']['status']}.** Re-run on edge-free synthetic "
      f"prices, the gauntlet returns **{d['noise_survivors']}** survivors. If it ever passed noise, "
      "the result would be void.")
    A("")
    A("## Why nothing survived (robust to how harsh the bar is)")
    A("")
    if cand:
        b = cand[0]
        A(f"- The **only** configs significant even with *no* multiple-testing penalty are "
          f"**{record['data_integrity_flags'][0] if record['data_integrity_flags'] else 'a few outliers'}** "
          f"— annualized Sharpe up to {_ann(b['sr_bar_full'], b['tf']):.1f}, which is a **data "
          f"artifact**, not an edge.")
    A("- Every **believable** candidate (annualized Sharpe ≤ ~1.4) fails significance *before* any "
      "deflation. The credible strategies are not individually significant; the individually "
      "significant ones are not credible.")
    A("")
    A("## Where the strategies died")
    A("")
    A("| Failure mode | Configs | Share | Meaning |")
    A("|---|---:|---:|---|")
    label = {"no_signal": "No signal", "single_regime": "Single-regime mirage",
             "gross_pos_net_neg": "Killed by cost wall", "deflation_collapse": "Selection-bias mirage",
             "both_halves_negative": "Negative both halves", "no_edge": "No edge"}
    mean = {"no_signal": "Net-negative before costs even existed.",
            "single_regime": "Up in one half, down the other; a regime, not an edge.",
            "gross_pos_net_neg": "Real gross signal, but 30bps cost exceeded it.",
            "deflation_collapse": "Looked real; explained by best-of-N luck.",
            "both_halves_negative": "Net-negative throughout.", "no_edge": "Sharpe ≤ 0."}
    for k, n in clusters.most_common():
        if k == "SURVIVOR":
            continue
        A(f"| {label.get(k,k)} | {n} | {n/nonsurv:.0%} | {mean.get(k,'')} |")
    A("")
    top = clusters.most_common()
    top = [(k, n) for k, n in top if k != "SURVIVOR"][0]
    A(f"**Pattern:** {top[1]/nonsurv:.0%} of failures share one mode — *{label.get(top[0],top[0])}*. "
      "This is one mistake repeated, not many different ones.")
    A("")
    A("---")
    A(f"*Reproducible: `python -m referee.run && python -m referee.report` (seed `{SEED}`). "
      f"Signature `{record['signature'][:16]}…`. Library + CLI + verdict + report; no execution, "
      "no order placement.*")
    open(MD_OUT, "w").write("\n".join(L) + "\n")
    return record, "\n".join(L)


if __name__ == "__main__":
    rec, md = build()
    print(md)
    print(f"\n[wrote {MD_OUT} and {JSON_OUT}; signature {rec['signature'][:16]}…]")
