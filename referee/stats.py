"""Statistics core for the gauntlet. numpy-only (no scipy in the container).

All Sharpe inputs here are PER-OBSERVATION (per-bar), not annualized. Annualize
only for display. T is the number of return observations.
"""
from __future__ import annotations
import math
import numpy as np

EULER_GAMMA = 0.5772156649015329


# ---------- normal CDF / inverse CDF (Acklam), no scipy ----------
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        num = ((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]
        den = (((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1
        return num / den
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        num = ((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]
        den = (((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1
        return -num / den
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ---------- per-bar Sharpe and its moments ----------
def sharpe_per_bar(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    return 0.0 if sd == 0 else float(r.mean() / sd)


def moments(returns: np.ndarray) -> tuple[float, float]:
    """returns (skew, kurtosis_NON_excess). Non-excess => normal == 3.0."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 4:
        return 0.0, 3.0
    m = r.mean()
    s = r.std(ddof=0)
    if s == 0:
        return 0.0, 3.0
    z = (r - m) / s
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))  # non-excess
    return skew, kurt


# ---------- expected max Sharpe under the null (no skill) ----------
def expected_max_sharpe(n_trials: int, var_trial_sharpe: float) -> float:
    """SR0 = E[max of N iid N(0,V) trial Sharpes] (Bailey & LdP 2014).
    SR0 = sqrt(V) * [ (1-gamma) * Z^-1(1 - 1/N) + gamma * Z^-1(1 - 1/(N e)) ].
    var_trial_sharpe V is the variance of per-bar trial Sharpes across the corpus.
    """
    N = max(int(n_trials), 2)
    V = max(float(var_trial_sharpe), 0.0)
    if V == 0.0:
        return 0.0
    z1 = norm_ppf(1.0 - 1.0 / N)
    z2 = norm_ppf(1.0 - 1.0 / (N * math.e))
    return math.sqrt(V) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


# ---------- Deflated Sharpe Ratio ----------
def deflated_sharpe(sr_per_bar: float, sr0_per_bar: float, T: int,
                    skew: float, kurt_non_excess: float) -> float:
    """DSR = Phi[ (SR - SR0) * sqrt(T-1) / sqrt(1 - skew*SR + ((kurt-1)/4)*SR^2) ].
    SR, SR0 are PER-BAR. Returns prob in [0,1]; >0.95 == statistically real."""
    if T < 2:
        return 0.0
    denom = 1.0 - skew * sr_per_bar + ((kurt_non_excess - 1.0) / 4.0) * sr_per_bar**2
    if denom <= 0:
        return 0.0
    z = (sr_per_bar - sr0_per_bar) * math.sqrt(T - 1) / math.sqrt(denom)
    return norm_cdf(z)


# ---------- Minimum Track Record Length ----------
def min_trl(sr_per_bar: float, sr_benchmark_per_bar: float, skew: float,
            kurt_non_excess: float, conf: float = 0.95) -> float:
    """Bars of track record needed for SR to beat SR* at confidence `conf`.
    MinTRL = 1 + [1 - skew*SR + ((kurt-1)/4)SR^2] * (Z_conf / (SR - SR*))^2.
    Returns inf when SR <= SR* (never significant)."""
    edge = sr_per_bar - sr_benchmark_per_bar
    if edge <= 0:
        return math.inf
    var_term = 1.0 - skew * sr_per_bar + ((kurt_non_excess - 1.0) / 4.0) * sr_per_bar**2
    if var_term <= 0:
        return math.inf
    z = norm_ppf(conf)
    return 1.0 + var_term * (z / edge) ** 2


# ---------- PBO via CSCV ----------
def _block_sharpe(sum_r, sum_r2, n):
    """Per-bar Sharpe over a concatenation of blocks, from pooled sums."""
    if n < 2:
        return -np.inf
    mean = sum_r / n
    var = sum_r2 / n - mean * mean
    if var <= 0:
        return -np.inf
    return mean / math.sqrt(var * n / (n - 1))


def pbo_cscv(block_sum_r: np.ndarray, block_sum_r2: np.ndarray,
             block_n: np.ndarray, S: int = 16, rng_seed: int = 0) -> dict:
    """Probability of Backtest Overfitting (Bailey-Borwein-LdP-Zhu 2017).

    Inputs are per-config, per-block pooled return statistics:
      block_sum_r[c,b], block_sum_r2[c,b], block_n[b]  (n is shared across configs
      on a common calendar grid; pass a (C,S) array if configs differ in coverage).
    Partition S blocks into all C(S,S/2) IS/OOS halves. For each split pick the
    IS-best config; record its OOS relative rank. PBO = P(OOS rank below median).
    """
    from itertools import combinations
    C, nb = block_sum_r.shape
    assert nb == S, f"expected {S} blocks, got {nb}"
    if block_n.ndim == 1:
        block_n = np.broadcast_to(block_n, (C, S))
    halves = list(combinations(range(S), S // 2))
    # CSCV uses complementary splits; iterate the first half of the symmetric set
    seen, logits, below = set(), [], 0
    n_splits = 0
    for IS in halves:
        OOS = tuple(b for b in range(S) if b not in IS)
        key = frozenset(IS)
        if key in seen or frozenset(OOS) in seen:
            continue
        seen.add(key)
        # IS performance of every config
        is_sr = np.empty(C)
        oos_sr = np.empty(C)
        for arr, blocks in ((is_sr, IS), (oos_sr, OOS)):
            sr = block_sum_r[:, blocks].sum(1)
            sr2 = block_sum_r2[:, blocks].sum(1)
            nn = block_n[:, blocks].sum(1)
            mean = np.divide(sr, nn, out=np.zeros(C), where=nn > 1)
            var = np.divide(sr2, nn, out=np.zeros(C), where=nn > 1) - mean*mean
            good = (nn > 1) & (var > 0)
            arr[:] = -np.inf
            arr[good] = mean[good] / np.sqrt(var[good] * nn[good] / (nn[good] - 1))
        n_star = int(np.argmax(is_sr))               # IS-best config
        # relative rank of n_star in OOS (1 = best, 0 = worst)
        finite = np.isfinite(oos_sr)
        order = oos_sr[finite]
        rank = (order < oos_sr[n_star]).sum() / max(finite.sum() - 1, 1)
        w = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))
        if rank <= 0.5:
            below += 1
        n_splits += 1
    pbo = below / n_splits if n_splits else float("nan")
    return {"pbo": pbo, "n_splits": n_splits, "S": S,
            "logit_mean": float(np.mean(logits)) if logits else float("nan")}
