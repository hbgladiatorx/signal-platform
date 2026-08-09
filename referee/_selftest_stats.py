"""Sanity battery for stats.py. Run inside the backtest container.
A real edge must clear DSR; a pure-noise corpus must sit at PBO~0.5, DSR<<0.95.
"""
import numpy as np
from referee import stats

rng = np.random.default_rng(42)
T = 21000
S = 16

# ---- 1. normal CDF/PPF round-trip ----
for p in (0.01, 0.25, 0.5, 0.84134, 0.95, 0.99):
    x = stats.norm_ppf(p)
    assert abs(stats.norm_cdf(x) - p) < 1e-4, (p, x, stats.norm_cdf(x))
assert abs(stats.norm_cdf(0) - 0.5) < 1e-9
print("1. norm cdf/ppf round-trip ....... OK")

# V (variance of per-bar trial Sharpes) is estimated empirically from a null
# ensemble, exactly as the real pipeline does it from the corpus.
N_TRIALS = 2450
null = rng.normal(0.0, 1.0, (N_TRIALS, T))
null_srs = (null.mean(1) / null.std(1, ddof=1))
V = float(null_srs.var(ddof=1))
sr0_big = stats.expected_max_sharpe(N_TRIALS, V)
sr0_small = stats.expected_max_sharpe(10, V)
print(f"   empirical V(per-bar trial SR)={V:.2e}  ~1/T={1/T:.2e}  "
      f"SR0(N=2450)={sr0_big:.4f}/bar")
# the BEST pure-null trial must NOT clear DSR (this is the deflation working)
best_null = int(np.argmax(null_srs))
sk0, ku0 = stats.moments(null[best_null])
dsr_bestnull = stats.deflated_sharpe(null_srs[best_null], sr0_big, T, sk0, ku0)
print(f"2. best-of-2450 NULL trial: SR/bar={null_srs[best_null]:.4f} "
      f"DSR={dsr_bestnull:.3f}  (must be < 0.95 -> deflation rejects luck)")
assert dsr_bestnull < 0.95, "deflation failed to reject the luckiest null trial"
assert sr0_big > sr0_small
print("   expected_max_sharpe monotone in N ... OK")

# ---- 3. a genuinely strong edge clears DSR even at honest N=2450 ----
strong = rng.normal(0.05, 1.0, T)          # per-bar SR ~0.05 (ann ~4.7) = huge
sr = stats.sharpe_per_bar(strong); sk, ku = stats.moments(strong)
dsr_strong = stats.deflated_sharpe(sr, sr0_big, T, sk, ku)
print(f"3. strong real edge: SR/bar={sr:.4f}  DSR(N=2450)={dsr_strong:.3f}  "
      f"(expect ~1.0)")
assert dsr_strong > 0.95

# ---- 4. NOISE BATTERY: C pure-noise configs -> PBO must be ~0.5 ----
C = 300
R = rng.normal(0.0, 1.0, (C, T))           # zero true edge, all configs
edges = np.linspace(-0.004, 0.004, C)      # tiny spurious spread of sample means
R += edges[:, None]
# build per-config, per-block pooled sums on a common grid
bnd = np.linspace(0, T, S + 1).astype(int)
sum_r = np.empty((C, S)); sum_r2 = np.empty((C, S)); bn = np.empty(S)
for b in range(S):
    seg = R[:, bnd[b]:bnd[b+1]]
    sum_r[:, b] = seg.sum(1); sum_r2[:, b] = (seg**2).sum(1); bn[b] = seg.shape[1]
res = stats.pbo_cscv(sum_r, sum_r2, bn, S=S)
print(f"4. NOISE battery: PBO={res['pbo']:.3f}  splits={res['n_splits']}  "
      f"logit_mean={res['logit_mean']:.3f}  (expect PBO 0.40-0.60)")
assert 0.35 <= res["pbo"] <= 0.65, "noise PBO not centered -> CSCV broken"

# ---- 5. a TRUE persistent edge embedded in noise -> PBO must drop LOW ----
R2 = rng.normal(0.0, 1.0, (C, T))
R2[0] += 0.06                              # config 0: real edge well above best null (~0.024)
sum_r = np.empty((C, S)); sum_r2 = np.empty((C, S))
for b in range(S):
    seg = R2[:, bnd[b]:bnd[b+1]]
    sum_r[:, b] = seg.sum(1); sum_r2[:, b] = (seg**2).sum(1)
res2 = stats.pbo_cscv(sum_r, sum_r2, bn, S=S)
print(f"5. real-edge corpus: PBO={res2['pbo']:.3f}  (expect LOW, <0.1)")
assert res2["pbo"] < 0.15, "real persistent edge should give low PBO"

# ---- 6. MinTRL sanity ----
trl = stats.min_trl(null_srs[best_null], 0.0, sk0, ku0)   # luckiest null vs zero
trl_strong = stats.min_trl(sr, 0.0, sk, ku)
print(f"6. MinTRL(best-null vs 0)={trl:,.0f} bars (>T, never significant)  "
      f"MinTRL(strong)={trl_strong:,.0f} vs T={T}")
assert stats.min_trl(0.0, 0.001, 0, 3) == np.inf  # no edge -> never

print("\nALL STATS SELFTESTS PASSED")
