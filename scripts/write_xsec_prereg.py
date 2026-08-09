#!/usr/bin/env python3
"""Build and sign app/logs/xsec_prereg.json (schema xsec.prereg/1).

Fixes every degree of freedom for the cross-sectional top-k momentum run BEFORE
any result exists. Signature = sha256 over the canonical content (all fields
except _sig), seeded, so the artifact regenerates byte-for-byte and any post-hoc
edit breaks the signature. This is the un-gameable filter: the lock is the asset.
"""
import json, hashlib

SEED = "xsec-prereg-v1-2026-06-27"
AS_OF = "2026-06-27"

# ---- prior program trial count (LOCKED, the figure the FUNDING verdict used) ----
# 3490 = 3400 price-on-close program + 90 funding sweep. Already includes everything
# tested before this run. No reset, no double-count, momentum-funding-spec counts 0.
PRIOR_PROGRAM_TRIALS = 3490

# ---- universe: widest CLEAN liquid set available in flat files (xr_1h.csv) ----
# Phase-0 audit (scripts/xsec_integrity.py -> xsec_data_integrity.json) passed all
# 12 majors (0 artifact jumps >50%/1h, 0 bad ticks, coverage >=99.52%, no stale
# run >12 bars). The broader screen_crypto_2yr list (SUI/ALGO/HBAR/...) is NOT
# ingested to flat files and obtaining it = new DB ingestion (out of scope), so the
# widest clean set on disk is these 12. BNB is INCLUDED here (price-momentum is
# eligible; its funding-axis exclusion was funding-mechanics-specific and does not
# apply to a price ranker). BCH and DOT carry the lowest coverage (62/67 1h gaps)
# but pass every disqualifying threshold; the single-name-dependence gate is the
# backstop if any survivor leans on one of them.
UNIVERSE = ["ADA", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETH",
            "LINK", "LTC", "SOL", "XRP"]
N_UNIV = len(UNIVERSE)

# ---- the TIGHT, capped grid (lookback cap 3, top-k cap 2, rebalance fixed) ----
LOOKBACKS_DAYS = [30, 60, 90]      # classic 1m/2m/3m cross-sectional formation horizons
TOP_K = [3, 5]                     # hold strongest 3 (25% of univ) or 5 (42%)
REBALANCE_DAYS = 7                 # weekly, FIXED (not swept) -> turnover low enough to survive cost
XSEC_TRIALS = len(LOOKBACKS_DAYS) * len(TOP_K)        # 6 configs, each one excess series
CUMULATIVE_TRIALS = PRIOR_PROGRAM_TRIALS + XSEC_TRIALS  # 3496

prereg = {
    "schema": "xsec.prereg/1",
    "seed": SEED,
    "as_of": AS_OF,
    "title": "Cross-sectional top-k momentum, long-only Binance.US spot, vs equal-weight basket",
    "status": "SIGNED & LOCKED; run exactly as signed, change nothing after results",

    "data": {
        "source": "app/logs/xr_1h.csv (12 majors, 2024-01-01..2026-06-22)",
        "integrity": "app/logs/xsec_data_integrity.json (Phase 0): all 12 CLEAN/FLAG, 0 dropped",
        "bar_construction": "1h OHLCV resampled to DAILY close (last 1h close of each UTC "
            "day); daily simple returns close->close; all symbols inner-joined to a common "
            "daily calendar so the cross-section is balanced every day.",
        "window_utc": ["2024-01-01", "2026-06-22"],
    },

    "universe": {
        "symbols": UNIVERSE, "n": N_UNIV,
        "selection": "Widest CLEAN liquid set in flat files. screen_crypto_2yr extras not "
                     "ingested (new DB ingestion = out of scope); 12 majors is the available "
                     "breadth and all passed Phase-0 integrity.",
        "notes": {
            "BNB": "INCLUDED for price momentum (funding-axis exclusion was mechanics-specific).",
            "BCH": "lowest coverage (99.61%, 62 1h gaps) but passes; watched by single-name gate.",
            "DOT": "lowest coverage (99.52%, 67 1h gaps) but passes; watched by single-name gate.",
        },
    },

    "signal": {
        "thesis_verbatim": "Cross-sectional momentum: assets that have outperformed their "
            "peers over a trailing formation window continue to outperform over the next "
            "holding window. This is a RELATIVE-strength question (rank the universe against "
            "itself), structurally different from every single-asset timing axis tested "
            "before, and the most robust documented systematic crypto edge. Long-only, spot.",
        "direction": "Each rebalance, rank the universe by trailing return over lookback L; "
            "hold the top-k equal-weight; flat the rest. Concentrate in relative winners.",
        "rule": {
            "rank_metric": "score_i(t) = close_i[t] / close_i[t-L] - 1  (trailing L-day return, "
                           "uses only closes through the ranking day t).",
            "selection": "pick the k symbols with the highest score; equal-weight 1/k each.",
            "rebalance": "every REBALANCE_DAYS (7) days on the daily grid; weights held "
                         "constant between rebalances.",
            "no_lookahead_assert": "weights decided at close t take effect on the NEXT day's "
                "return (W_eff = W_held.shift(1)); the strategy never earns the return of the "
                "bar whose close set the ranking. Mirrors referee/corpus pos.shift(1).",
            "weight_set": "0 for unheld names, 1/k for held names; long-only, sum<=1.",
        },
        "grid": {
            "lookback_days": LOOKBACKS_DAYS,
            "top_k": TOP_K,
            "rebalance_days": REBALANCE_DAYS,
            "rebalance_is_swept": False,
        },
        "config_count": {"lookbacks": len(LOOKBACKS_DAYS), "top_k_values": len(TOP_K),
                         "total_xsec_trials": XSEC_TRIALS},
        "warmup_days": max(LOOKBACKS_DAYS),
    },

    "n_trials": {
        "rule": "Honest cumulative n_trials = full prior program (3490, the figure the funding "
                "verdict used) + this sweep (6). No reset to N=1. No double-count.",
        "prior_program_trials": PRIOR_PROGRAM_TRIALS,
        "prior_breakdown": "3400 price-on-close program + 90 funding sweep = 3490",
        "xsec_trials": XSEC_TRIALS,
        "cumulative_n_trials": CUMULATIVE_TRIALS,
        "deflation_uses": CUMULATIVE_TRIALS,
        "effective_trials_diagnostic": "Raw cumulative (3496) is used for deflation "
            "(conservative). The 6 xsec configs are correlated (same universe, overlapping "
            "lookbacks/holdings) so effective INDEPENDENT new trials < 6, but deflating at the "
            "full 3496 is the harder choice and is what feeds the verdict.",
    },

    "benchmark": {
        "null_to_beat": "EQUAL-WEIGHT buy-and-hold of the SAME universe, NOT zero and NOT cash.",
        "definition": "bench_ret_t = mean over all N universe symbols of their daily return on "
            "day t (daily equal-weight index), COSTLESS. Charging the passive benchmark no cost "
            "while the strategy pays full turnover is the conservative choice: it makes beating "
            "the benchmark HARDER, so cost can never be blamed for a pass and a frictionless "
            "diversified hold can never be flattered into a loss.",
        "construction_locked": "The series fed to the gauntlet is EXCESS over the equal-weight "
            "basket, per day: excess_t = port_ret_t - cost_t - bench_ret_t, where "
            "port_ret_t = sum_i W_eff[t,i]*ret_i[t] (W_eff = held 1/k weights shifted 1 day), "
            "cost_t = turnover_t * COST_SIDE (turnover = sum_i |W_eff[t,i]-W_eff[t-1,i]|, which "
            "is the name-rotation cost concentrated the day after each weekly rebalance; "
            "COST_SIDE = 0.0015 = 30bps round-trip locked). 'positive both halves' therefore "
            "MEANS 'beats equal-weight B&H both halves'; DSR on excess_t MEANS the "
            "out-performance over naive diversification is real after deflation; min_trl uses "
            "benchmark 0 because the series is already excess. No referee threshold changes.",
        "deploy_requires": "Beating the equal-weight basket on a deflation- and PBO-aware basis "
            "(DSR(excess)>0.95 at n=3496, both halves, PBO<0.50), not merely being positive and "
            "not merely beating cash.",
        "raw_reporting": "Raw strategy total return, basket total return, turnover and trade "
            "count reported alongside for transparency; the DEPLOY decision is on the excess "
            "series.",
        "prior_warning": "Genuinely uncertain prior (stop-and-ask item): cross-sectional "
            "momentum is the most robust documented crypto edge, so this has a REAL shot -- the "
            "first axis tested here that is not single-asset timing. BUT (a) a 12-name universe "
            "of highly-correlated majors is a THIN, low-dispersion cross-section that weakens "
            "relative-strength signal; (b) weekly turnover at 30bps round-trip can still eat a "
            "modest edge; (c) the benchmark is itself a strong long crypto basket over a "
            "2024-26 up-market, so concentrating must beat broad beta. A clean null is a real "
            "possibility and would be reported as a finding, not massaged into a pass.",
    },

    "cost_and_venue": {
        "cost_model": {"fee_bps_per_side": 10, "slip_bps_per_side": 5, "round_trip_bps": 30,
                       "COST_SIDE": 0.0015,
                       "label": "Conservative honest Binance.US USD spot, identical to the price "
                                "corpus and funding run. Applied to turnover; NOT discounted."},
        "venue_note": "Long-only spot, top-k equal-weight; fully expressible as a platform "
                      "strategy (periodic rank-and-hold). No shorting, no perp, no leverage.",
    },

    "gauntlet": {
        "engine": "app/referee/ (unmodified referee.stats / referee.verdict / referee.noise), "
                  "schema referee.verdict/1. Same math as the matrix50 corpus and funding runs.",
        "net_of_cost": True,
        "tests": ["DSR (deflated Sharpe, Bailey-LdP)", "PBO via CSCV (Bailey-Borwein-LdP-Zhu)",
                  "MinTRL", "purge+embargo", "both-halves", "regime conditioning 2024/2025",
                  "single-name dependence", "noise battery"],
        "cscv_blocks_S": 16,
        "embargo_days": 14,
        "embargo_reasoning": "14 days = 2 weekly rebalance cycles. The CSCV concern is shared "
            "information across IS/OOS block boundaries; for a weekly-rebalanced book the "
            "binding autocorrelation is at the rebalance scale, so a 2-cycle embargo purges the "
            "overlap. The 90-day ranking lookback uses only already-realized past closes. "
            "Embargo is kept << block length (~50 daily bars at S=16) so blocks are not emptied "
            "(the funding run's 270-bar embargo degenerated PBO; this is the corrected choice).",
        "both_halves_split": "chronological midpoint of the post-warmup daily excess series; "
                             "both halves on excess_t.",
        "regime_conditioning": "Excess sum reported per calendar year 2024 / 2025 / 2026-partial. "
            "A config positive in only one calendar year = single_regime, not DEPLOY.",
        "single_name_dependence": "For any DEPLOY candidate, recompute total excess with each "
            "universe symbol removed in turn (leave-one-out of the RANKING pool). If dropping "
            "any single name (or any two) flips total excess <=0, the config is single-name "
            "dependent => HOLD_CONDITIONAL, never DEPLOY.",
        "noise_battery": "referee.noise.make_null_logs builds block-bootstrapped, demeaned "
            "null 1h prices for the universe; the cross-sectional strategy run on them must "
            "yield 0 null survivors (GREEN). If any synthetic null clears DSR>0.95, HALT -- the "
            "engine finds rank-momentum in noise -- do not report a pass.",
        "thresholds": {
            "DSR_BAR": 0.95, "PBO_BAR": 0.50,
            "MinTRL_rule": "min_trl <= T (post-warmup daily bars per config)",
            "DEPLOY": "PBO_corpus<0.50 AND noise GREEN AND exists config with: both halves "
                "excess>0 AND excess_sr_bar>0 AND DSR(excess,n=3496)>0.95 AND MinTRL<=T AND "
                "both calendar years (2024,2025) positive AND NOT single-name dependent.",
            "HOLD_CONDITIONAL": "A config clears DSR(excess)>0.95 and beats the basket both "
                "halves but is single-regime OR single-name dependent. Surfaced for the human "
                "call; never auto-DEPLOY.",
            "REJECT": "No config clears DSR(excess)>0.95, OR every config fails both-halves-vs-"
                "basket, OR PBO_corpus>=0.50, OR noise battery not GREEN. => the cross-sectional "
                "axis is closed with a clean, rigorous null.",
        },
        "verdict_output": "app/logs/xsec_verdict_signed.json, schema referee.verdict/1, seeded "
                          "with this prereg seed, same signed schema as the corpus & funding runs.",
    },

    "stop_and_ask": [
        "Universe integrity issue on any symbol surfacing later -> flag and drop before ranking, "
        "record it; do not silently keep a dirty symbol.",
        "A survivor that is single-regime or depends on one or two names -> flag "
        "HOLD_CONDITIONAL, do not DEPLOY, surface it.",
        "Noise battery flips to passing, or any signature mismatch -> HALT.",
        "Any urge to widen the grid (more lookbacks/top-k, change rebalance) or relax a "
        "threshold to manufacture a pass -> STOP and ask. A forced survivor is worth less than "
        "an honest null.",
    ],

    "out_of_scope": ["no execution / broker / order path", "no marketplace / signals / mockData",
                     "no ML / meta-labeling (stays conditional on a SURVIVING primary; the "
                     "human's call after reading the primary verdict)",
                     "no shorting (long-only spot)", "do not touch the dead price or funding "
                     "corpora; do not re-run superseded specs"],
}


def sign(rec, seed):
    payload = json.dumps(rec, sort_keys=True, default=float).encode()
    return hashlib.sha256(seed.encode() + payload).hexdigest()


prereg["_sig"] = sign(prereg, SEED)
out = "/home/signal/app/logs/xsec_prereg.json"
with open(out, "w") as f:
    json.dump(prereg, f, indent=2)
print(json.dumps(prereg, indent=2))
print("\nwrote", out, "  sig", prereg["_sig"][:16], "...")
