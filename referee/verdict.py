"""The gauntlet: turn the corpus into honest verdicts + failure clusters.

DEPLOY requires ALL of:
  - both-halves net-positive (regime robustness, not a single-regime mirage)
  - net per-bar Sharpe > 0
  - Deflated Sharpe > 0.95 with n_trials = the FULL program trial count
  - MinTRL <= T (enough track record to be significant)
and the corpus-level PBO must be below 0.5 for the run to be trustworthy at all.

A config that clears everything but lives in one symbol/regime is CONDITIONAL,
never DEPLOY, and is surfaced for a human call.
"""
from __future__ import annotations
import hashlib, json
import numpy as np
from referee import stats

DSR_BAR = 0.95
PBO_BAR = 0.50


def program_trial_count(logs="/app/logs") -> dict:
    """Honest n_trials = distinct strategy configs the search ever evaluated.
    Counts rows across the matrix/sweep families (excludes LLM meta caches and
    mock runs). Returns both the scored-pool size and the program size."""
    import glob, os
    families = {}
    for path in sorted(glob.glob(f"{logs}/*.jsonl")):
        name = os.path.basename(path)
        if "meta_cache" in name or "mock" in name or "smoke" in name:
            continue
        n = sum(1 for _ in open(path))
        families[name] = n
    program = sum(families.values())
    return {"families": families, "program_trials": program}


def evaluate(corpus: dict, n_trials_program: int) -> dict:
    ids, meta = corpus["ids"], corpus["meta"]
    C = len(ids)
    V = float(np.var(corpus["sr_bar"], ddof=1))
    sr0 = stats.expected_max_sharpe(n_trials_program, V)

    # corpus-level PBO (overfitting of the whole search)
    pbo = stats.pbo_cscv(corpus["block_sum_r"], corpus["block_sum_r2"],
                         corpus["block_n"], S=corpus["S"])

    rows = []
    for i in range(C):
        m = meta[i]
        T = m["T"]; srb = m["sr_bar_full"]
        dsr = stats.deflated_sharpe(srb, sr0, T, m["skew"], m["kurt"])
        trl = stats.min_trl(srb, 0.0, m["skew"], m["kurt"])
        both = (m["ret_h1"] > 0) and (m["ret_h2"] > 0)
        rows.append({**m, "id": ids[i], "dsr": dsr, "sr0_bar": sr0,
                     "min_trl": trl, "trl_ok": trl <= T, "both_halves": both,
                     "deploy": bool(both and srb > 0 and dsr > DSR_BAR and trl <= T)})
    return {"n_pool": C, "n_trials_program": n_trials_program, "V": V,
            "sr0_bar": sr0, "pbo": pbo, "rows": rows, "dsr_bar": DSR_BAR}


def classify_failure(r: dict) -> str:
    """Single dominant failure mode for the kill-list clustering."""
    if r["deploy"]:
        return "SURVIVOR"
    h1, h2, g = r["ret_h1"], r["ret_h2"], r["ret_gross_full"]
    net = r["ret_full"]
    if r["both_halves"] and r["sr_bar_full"] > 0 and r["dsr"] <= 0.95:
        return "deflation_collapse"          # real-looking, killed by trial count
    if (h1 > 0) != (h2 > 0):
        return "single_regime"               # one half up, one down = mirage
    if g > 0 and net < 0:
        return "gross_pos_net_neg"           # had signal, cost wall ate it
    if g <= 0:
        return "no_signal"                    # negative even before costs
    if r["min_trl"] == float("inf"):
        return "no_edge"
    return "both_halves_negative"


def sign_record(rec: dict, seed: str) -> dict:
    """Deterministic content signature so a verdict regenerates from a seed."""
    payload = json.dumps(rec, sort_keys=True, default=float).encode()
    sig = hashlib.sha256(seed.encode() + payload).hexdigest()
    return {**rec, "_seed": seed, "_sig": sig}
