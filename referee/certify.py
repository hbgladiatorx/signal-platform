"""Run the unchanged gauntlet on an external strategy submission.

Same frozen pipeline and thresholds as our own runs (referee.stats /
referee.verdict): net-of-cost returns, Deflated Sharpe vs the deflated benchmark
at the declared (or floor-corrected) trial count, PBO via CSCV when a config
matrix is supplied, MinTRL vs T, both-halves, regime conditioning, and a
per-submission noise battery. The verdict is one of:

  DEPLOY            — clears every gate, regime-robust.
  HOLD_CONDITIONAL  — clears DSR + both-halves + MinTRL + noise but is
                      single-regime, or PBO is borderline. A human call.
  REJECT            — fails a hard gate (most submissions land here; that is the
                      product working, not failing).
  UNVERIFIABLE      — the data could not be trusted (integrity), so no grade is
                      issued. Set upstream by intake; honored here.

No customer override of any threshold. DSR_BAR / PBO_BAR are imported from
referee.verdict so a single source of truth governs our runs and customers' alike.
"""
from __future__ import annotations

import hashlib

import numpy as np

from referee import stats
from referee.verdict import DSR_BAR, PBO_BAR
from referee.intake import Submission, check_integrity, estimate_trial_floor


def _sharpe_estimator_var(sr_bar: float, T: int, skew: float, kurt: float) -> float:
    """Asymptotic variance of the Sharpe-ratio ESTIMATOR (per-bar), used as the
    plug-in V for SR0 when only a single series is submitted (no cross-section of
    trial Sharpes to measure variance directly). This is the standard fallback:
    under the null the spread of trial Sharpes is the estimator's own sampling
    variance. With a real config matrix we measure V directly instead."""
    if T < 2:
        return 0.0
    var_term = 1.0 - skew * sr_bar + ((kurt - 1.0) / 4.0) * sr_bar ** 2
    return max(var_term, 1e-9) / (T - 1)


def _block_bootstrap(x: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    T = x.size
    idx = []
    while len(idx) < T:
        s = int(rng.integers(0, max(T - block, 1)))
        idx.extend(range(s, min(s + block, T)))
    return x[np.array(idx[:T])]


# Green line for the bootstrap noise battery, DERIVED from the frozen DSR_BAR (not
# an independent knob). A DSR>0.95 test is a 95%-confidence / 5%-tail test by
# construction, so under a demeaned (edge-free) null it is *expected* to false-
# positive up to (1 - DSR_BAR) of the time; demanding 0 would require the test to
# be stricter than its own stated level. We therefore call the battery GREEN when
# the full-deploy-gate null survival rate stays at or below that nominal level. A
# genuine distribution-shape artifact (fat tails / autocorrelation that inflate
# DSR) SURVIVES demeaning and drives the rate well past 5%, so this still catches
# the artifact it is meant to catch. Tied to DSR_BAR => one source of truth.
NOISE_MAX_NULL_RATE = round(1.0 - DSR_BAR, 6)   # 0.05


def _noise_battery(excess: np.ndarray, n_trials: int, V: float, *, n_boot: int,
                   seed: int) -> dict:
    """Per-submission null: block-bootstrap the DEMEANED returns (kills the edge,
    keeps volatility + autocorrelation + fat tails), then run the FULL deploy gate
    at the same trial count — the exact analog of the corpus battery. A green
    battery proves the verdict is driven by drift (the edge), not by the series'
    distribution shape (fat tails / autocorrelation)."""
    demeaned = excess - np.nanmean(excess)
    block = max(5, int(round(np.sqrt(excess.size))))
    rng = np.random.default_rng(seed)
    sr0 = stats.expected_max_sharpe(n_trials, V)
    survivors = 0
    max_dsr = 0.0
    for _ in range(n_boot):
        b = _block_bootstrap(demeaned, block, rng)
        srb = stats.sharpe_per_bar(b)
        sk, ku = stats.moments(b)
        d = stats.deflated_sharpe(srb, sr0, b.size, sk, ku)
        max_dsr = max(max_dsr, d)
        mid = b.size // 2
        both = (b[:mid].sum() > 0) and (b[mid:].sum() > 0)
        trl = stats.min_trl(srb, 0.0, sk, ku)
        if srb > 0 and both and d > DSR_BAR and trl <= b.size:   # full deploy gate
            survivors += 1
    rate = survivors / n_boot
    return {"n_boot": n_boot, "block": block, "null_passes": survivors,
            "null_pass_rate": rate, "max_null_dsr": float(max_dsr),
            "tolerance": NOISE_MAX_NULL_RATE,
            "status": "GREEN" if rate <= NOISE_MAX_NULL_RATE else "BROKEN"}


def _pbo_from_matrix(matrix: np.ndarray, S: int, embargo: int) -> dict | None:
    """CSCV PBO across the submitted config matrix (T x C of per-bar excess).
    Only meaningful with >= 2 configs."""
    if matrix is None or matrix.ndim != 2 or matrix.shape[1] < 2:
        return None
    T, C = matrix.shape
    blk = np.clip((np.arange(T) / T * S).astype(int), 0, S - 1)
    bsr = np.zeros((C, S)); bsr2 = np.zeros((C, S)); bn = np.zeros((C, S))
    for c in range(C):
        x = matrix[:, c]
        # embargo first `embargo` bars of each block
        idx = np.arange(T)
        change = np.empty(T, bool); change[0] = True; change[1:] = blk[1:] != blk[:-1]
        start = np.maximum.accumulate(np.where(change, idx, 0))
        keep = (idx - start) >= embargo
        for b in range(S):
            msk = keep & (blk == b)
            if msk.any():
                seg = x[msk]
                bsr[c, b] = seg.sum(); bsr2[c, b] = (seg**2).sum(); bn[c, b] = seg.size
    return stats.pbo_cscv(bsr, bsr2, bn, S=S)


def certify(sub: Submission, *, benchmark_returns: np.ndarray | None = None,
            config_matrix: np.ndarray | None = None, declared_grid_size: int | None = None,
            seed: str = "referee-cert-v1", n_boot: int = 200, S: int = 16,
            embargo: int = 5) -> dict:
    """Grade a normalized submission. Returns the full verdict record (unsigned)."""
    integrity = check_integrity(sub)

    n_cfg = int(config_matrix.shape[1]) if (config_matrix is not None
                                            and config_matrix.ndim == 2) else 0
    trials = estimate_trial_floor(sub, n_config_series=n_cfg,
                                  declared_grid_size=declared_grid_size)
    n_trials = trials["n_trials_used"]

    base = {
        "schema": "referee.cert/1",
        "seed": seed,
        "format": sub.fmt,
        "n_obs": sub.n_obs,
        "cost_model": {"round_trip_bps": sub.cost_bps, "applied": sub.cost_applied,
                       "label": ("deducted per trade" if sub.cost_applied
                                 else "submitter-declared, returns taken as net"),
                       "self_declared": True},
        "trials": trials,
        "integrity": integrity,
        "notes": sub.notes,
    }

    if integrity["status"] == "UNVERIFIABLE":
        base.update(verdict="UNVERIFIABLE",
                    narrative="Submission failed data-integrity checks; no grade issued. "
                              + " ".join(integrity["reasons"]))
        return base

    # ----- net excess series (vs supplied benchmark, else vs cash/0) -----
    r = sub.returns.astype(float)
    if benchmark_returns is not None:
        bench = np.asarray(benchmark_returns, float)
        if bench.size != r.size:
            base.update(verdict="UNVERIFIABLE",
                        narrative=f"benchmark length {bench.size} != returns length {r.size}")
            return base
        excess = r - bench
        bench_label = "supplied benchmark series (excess)"
    else:
        excess = r
        bench_label = "cash / zero (absolute net returns)"

    T = excess.size
    mid = T // 2
    sr_bar = stats.sharpe_per_bar(excess)
    skew, kurt = stats.moments(excess)
    ann_sharpe = sr_bar * np.sqrt(sub.periods_per_year)

    # ----- deflation: V from the matrix if given, else estimator-variance plug-in -----
    if n_cfg >= 2:
        per_cfg_sr = np.array([stats.sharpe_per_bar(config_matrix[:, c]) for c in range(n_cfg)])
        V = float(np.var(per_cfg_sr, ddof=1))
        v_basis = f"variance across {n_cfg} submitted config Sharpes"
    else:
        V = _sharpe_estimator_var(sr_bar, T, skew, kurt)
        v_basis = "Sharpe-estimator sampling variance (single series; no config matrix)"
    sr0 = stats.expected_max_sharpe(n_trials, V)
    dsr = stats.deflated_sharpe(sr_bar, sr0, T, skew, kurt)
    trl = stats.min_trl(sr_bar, 0.0, skew, kurt)
    trl_ok = trl <= T

    h1, h2 = float(excess[:mid].sum()), float(excess[mid:].sum())
    both_halves = (h1 > 0) and (h2 > 0)

    # ----- regime conditioning by calendar year (if timestamped) -----
    regime = {}
    both_calendar_pos = True
    if sub.timestamps is not None:
        years = sub.timestamps.year.to_numpy()
        for y in np.unique(years):
            regime[int(y)] = float(excess[years == y].sum())
        full_years = [y for y in regime if (years == y).sum() >= sub.periods_per_year * 0.5]
        if len(full_years) >= 2:
            both_calendar_pos = all(regime[y] > 0 for y in full_years)
    else:
        both_calendar_pos = both_halves  # no calendar -> fall back to halves

    # ----- PBO (only when a config matrix is supplied) -----
    pbo = _pbo_from_matrix(config_matrix, S=S, embargo=embargo)
    pbo_ok = (pbo is None) or (pbo["pbo"] < PBO_BAR)

    # ----- noise battery on this submission -----
    # deterministic RNG seed from the report seed (hashlib, NOT Python's per-process
    # randomized hash()) so the noise results — and thus the signed content_hash —
    # regenerate identically from the same seed.
    rng_seed = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big")
    noise = _noise_battery(excess, n_trials, V, n_boot=n_boot, seed=rng_seed)

    # ----- frozen gates -----
    passes_core = bool(both_halves and sr_bar > 0 and dsr > DSR_BAR and trl_ok)
    if noise["status"] != "GREEN":
        verdict = "UNVERIFIABLE"
        narrative = ("Noise battery not green: the gauntlet found apparent edge in the "
                     "demeaned bootstrap of these returns, so the Sharpe is an artifact of "
                     "the distribution's shape (fat tails / autocorrelation), not a real "
                     "edge. No grade issued.")
    elif passes_core and pbo_ok and both_calendar_pos:
        verdict = "DEPLOY"
        _tw = "trial" if n_trials == 1 else "trials"
        narrative = ("Clears every gate net of cost and deflated against "
                     f"{n_trials} {_tw}: DSR {dsr:.3f} > {DSR_BAR}, positive in both halves, "
                     f"MinTRL {trl:.0f} <= T {T}, regime-robust, noise battery GREEN.")
    elif passes_core and (not pbo_ok or not both_calendar_pos):
        verdict = "HOLD_CONDITIONAL"
        why = []
        if not both_calendar_pos:
            why.append("negative in at least one full calendar year (single-regime)")
        if not pbo_ok:
            why.append(f"PBO {pbo['pbo']:.2f} >= {PBO_BAR} (config search looks overfit)")
        narrative = ("Clears DSR, both-halves and MinTRL but is " + "; ".join(why) +
                     ". A human call, never auto-deploy.")
    else:
        verdict = "REJECT"
        fails = []
        if sr_bar <= 0:
            fails.append("net Sharpe <= 0")
        if not both_halves:
            fails.append(f"not positive in both halves (H1={h1:.4f}, H2={h2:.4f})")
        if dsr <= DSR_BAR:
            fails.append(f"DSR {dsr:.3f} <= {DSR_BAR} at n_trials={n_trials} "
                         "(not significant after deflation)")
        if not trl_ok:
            fails.append(f"MinTRL {trl:.0f} > T {T} (track record too short to be significant)")
        narrative = "Fails the bar: " + "; ".join(fails) + "."

    base.update(
        verdict=verdict, narrative=narrative,
        benchmark=bench_label,
        metrics={
            "T": T, "net_sharpe_per_bar": float(sr_bar),
            "net_sharpe_annualized": float(ann_sharpe),
            "periods_per_year": sub.periods_per_year,
            "skew": float(skew), "kurt_non_excess": float(kurt),
            "dsr": float(dsr), "dsr_bar": DSR_BAR,
            "sr0_per_bar": float(sr0), "deflation_V": float(V), "deflation_V_basis": v_basis,
            "min_trl": (float(trl) if np.isfinite(trl) else None), "T_obs": T, "trl_ok": trl_ok,
            "ret_h1": h1, "ret_h2": h2, "both_halves": both_halves,
            "regime": regime, "both_calendar_pos": both_calendar_pos,
            "total_return_pct": float((np.prod(1 + r) - 1) * 100),
        },
        pbo_cscv=(None if pbo is None else
                  {"pbo": pbo["pbo"], "n_splits": pbo["n_splits"], "S": pbo["S"], "bar": PBO_BAR}),
        noise_battery=noise,
        n_trials_for_deflation=n_trials,
    )
    return base
