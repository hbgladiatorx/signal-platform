#!/usr/bin/env python3
"""Build and sign app/logs/funding_prereg.json (schema funding.prereg/1).

Fixes every degree of freedom for the Phase-1 funding-gated long/flat spot run
BEFORE any result exists. The signature is a sha256 over the canonical content
(all fields except _sig), seeded, so the artifact regenerates byte-for-byte and
any post-hoc edit breaks the signature.
"""
import json, hashlib

SEED = "funding-prereg-v1-2026-06-27"
AS_OF = "2026-06-27"

# ---- enumerate the existing program trial families (referee program count) ----
# Counts mirror referee.verdict.program_trial_count(): all *.jsonl in logs EXCEPT
# meta_cache* / *mock / *smoke. Sum == 3400, the figure the matrix50 verdict used.
PROGRAM_FAMILIES = {
    "donchian_full": 14, "donchian_slow": 25, "matrix50_robust": 1200,
    "matrix_5m_pilot": 70, "matrix_5m_rest": 204, "matrix_BTC": 0,
    "matrix_btc_2yr": 102, "matrix_strats": 183, "matrix_strats2": 800,
    "matrix_strats_15m": 408, "matrix_strats_5m": 183, "meta_ab": 12,
    "oos_doge": 16, "oos_donchian": 36, "survivor_2yr_revalidation": 9,
    "survivor_2yr_revalidation_deployedcfg": 9, "vec_donchian_2yr": 96,
    "vec_uo_2yr": 12, "vec_xreversal": 9, "vec_xreversal_autocorr": 12,
}
PROGRAM_TRIALS = sum(PROGRAM_FAMILIES.values())   # == 3400

UNIVERSE = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC"]

# ---- the TIGHT, capped grid (item 3) ----
LOOKBACKS = [21, 90, 270]          # 8h settlements ~ 7d / 30d / 90d crowding horizons
MARGINS = [5e-5, 1e-4, 2e-4]       # funding/8h added on top of trailing mean: 0.5/1.0/2.0 bp
HYSTERESIS = 5e-5                  # single pre-registered exit-band constant (0.5 bp), NOT swept

SIGNAL_CONFIGS = len(LOOKBACKS) * len(MARGINS)        # 9 per symbol
PER_SYMBOL_CELLS = SIGNAL_CONFIGS * len(UNIVERSE)     # 81
BASKET_CELLS = SIGNAL_CONFIGS                         # 9 (equal-weight basket under each config)
FUNDING_TRIALS = PER_SYMBOL_CELLS + BASKET_CELLS      # 90
CUMULATIVE_TRIALS = PROGRAM_TRIALS + FUNDING_TRIALS   # 3490

prereg = {
    "schema": "funding.prereg/1",
    "seed": SEED,
    "as_of": AS_OF,
    "title": "Phase 1 pre-registration: funding-gated long/flat Binance.US spot",
    "status": "SIGNED-PENDING-HUMAN-SIGNOFF; run nothing until countersigned",

    "data": {
        "source": "app/logs/perp/<SYM>_funding_full.csv",
        "integrity": "app/logs/funding_data_integrity.json (Phase 0, CLEAN_WITH_FLAGS)",
        "window_utc": ["2024-01-01 00:00", "2026-06-01 00:00"],
        "settlements_per_symbol": 2646,
        "bar": "8h funding period; spot returns measured close->close on Binance.US "
               "USD pairs on 8h bars aligned to the 00/08/16 UTC funding clock",
    },

    "universe": {
        "symbols": UNIVERSE,
        "n": len(UNIVERSE),
        "excluded": {
            "BNB": "Degenerate funding mechanics: funding == 0 for ~60% of settlements "
                   "(longest zero-run 81), mean funding NEGATIVE (-1.94%/yr), only 23% "
                   "of settlements positive. It is not a weak version of the signal, it "
                   "is a different signal. Excluded a priori; not to be slipped back in."
        },
    },

    "signal": {
        "thesis_verbatim": "Persistently positive funding is a crowding and leverage-"
            "demand signal with no reason to be priced into spot close. Trade spot, "
            "long/flat only (no perp => never pay funding ourselves; no short => no borrow).",
        "direction": "LONG when funding is ELEVATED vs its own trailing mean; FLAT otherwise.",
        "base_rate_constraint": "Naive funding>0 fires during calm 0.0001 base-rate periods "
            "which are bull-regime-correlated -> would manufacture a long-the-bull edge in a "
            "funding costume (single_regime reincarnated). Signal is funding ABOVE its own "
            "trailing mean PLUS a margin, never funding above zero.",
        "rule": {
            "trailing_mean_t": "m_t = mean(funding[t-L+1 .. t]); uses only data through "
                "settlement t (known at the bar boundary).",
            "enter_long_for_bar_tplus1_if": "state==flat AND funding_t >= m_t + margin",
            "exit_to_flat_for_bar_tplus1_if": "state==long AND funding_t < m_t - hysteresis",
            "else": "hold current state",
            "no_lookahead_assert": "Position acts on bar t+1 (the 8h spot bar STRICTLY AFTER "
                "settlement t). It may never act on the bar containing the settlement ts. "
                "Implemented as pos.shift(1), matching referee/corpus.py.",
            "position_set": [0, 1],
        },
        "grid": {
            "trailing_mean_lookback_settlements": LOOKBACKS,
            "margin_funding_per_8h": MARGINS,
            "hysteresis_funding_per_8h": HYSTERESIS,
            "hysteresis_is_swept": False,
        },
        "config_count": {
            "signal_configs_per_symbol": SIGNAL_CONFIGS,
            "per_symbol_cells": PER_SYMBOL_CELLS,
            "basket_cells": BASKET_CELLS,
            "total_funding_trials": FUNDING_TRIALS,
        },
        "warmup_bars": max(LOOKBACKS),
        "min_T_after_warmup": 2646 - max(LOOKBACKS),   # ~2376 bars/config
    },

    "n_trials": {
        "rule": "Honest n_trials = full program count + this funding sweep. No reset to N=1.",
        "program_families": PROGRAM_FAMILIES,
        "program_trials": PROGRAM_TRIALS,
        "funding_trials": FUNDING_TRIALS,
        "cumulative_n_trials": CUMULATIVE_TRIALS,
        "deflation_uses": CUMULATIVE_TRIALS,
        "effective_trials_diagnostic": "Raw cumulative (3490) is used for deflation "
            "(conservative). NOTE the 81 per-symbol cells share only 9 distinct "
            "parameterizations across 9 correlated symbols, so effective INDEPENDENT funding "
            "trials < 81. We deflate against the RAW 3490 anyway (harder to pass). If an "
            "effective-trials estimate diverges materially from 3490 at verdict time, BOTH "
            "are reported with reasoning before they feed the verdict (stop-and-ask).",
    },

    "benchmark": {
        "null_to_beat": "BUY-AND-HOLD long/flat spot over the identical window, NOT zero.",
        "per_symbol": "long-only buy-and-hold of each symbol over the window.",
        "basket": "equal-weight buy-and-hold of the 9 symbols, daily/8h rebalanced, "
                  "over the window.",
        "construction_locked": "The series fed to the gauntlet is EXCESS over buy-and-hold, "
            "per bar: excess_t = (pos_{t-1} - 1)*ret_t - cost_t, pos in {0,1}. When long, "
            "excess = -cost (transition bars only); when flat, excess = -ret (the bar's "
            "return forgone). Therefore 'positive both halves' MEANS 'beats B&H both halves', "
            "DSR on excess_t MEANS the out-performance is real after deflation, and "
            "min_trl uses benchmark 0 because the series is already excess. No referee "
            "threshold is changed; only the input series definition differs from the price "
            "corpus (which benchmarked vs cash).",
        "deploy_requires": "Beating buy-and-hold on a deflation- and PBO-aware basis "
            "(DSR(excess)>0.95 at n=3490, both halves, PBO<0.50), not merely being positive "
            "and not merely beating zero.",
        "raw_reporting": "Raw (non-excess) gate return, trade count, and B&H return are "
            "reported alongside for transparency; the DEPLOY decision is on the excess series.",
        "prior_warning": "Pre-registered honest prior (stop-and-ask item): 2024-01..2026-06 "
            "was net strongly positive for crypto B&H with large drawdowns. A LONG-when-"
            "funding-elevated gate is structurally at risk of being long into euphoric "
            "high-funding tops and FLAT through negative-funding recoveries -- i.e. it can "
            "miss exactly the rebounds that make crypto returns. Beating B&H is therefore a "
            "HIGH bar and the clean NULL is the most likely outcome. This is stated before "
            "the run so a null is not a surprise and a survivor faces full scrutiny.",
    },

    "cost_and_venue": {
        "cost_model": {"fee_bps_per_side": 10, "slip_bps_per_side": 5,
                       "round_trip_bps": 30,
                       "label": "Conservative, honest Binance.US USD spot. NOT reduced for "
                                "spot being cheaper than the perp round-trip, deliberately, "
                                "so cost can never be blamed for a pass. Identical to the "
                                "price-corpus COST_SIDE."},
        "venue_note_verbatim": "Signal is Binance GLOBAL USDT-perp funding; tradable is "
            "Binance.US USD SPOT; thesis is dominant-venue funding as a venue-agnostic "
            "crowding predictor. Documented so it is never mistaken for same-venue funding "
            "capture.",
    },

    "gauntlet": {
        "engine": "app/referee/ (schema referee.verdict/1), funding family adds "
                  "logs/funding_gated.jsonl (exactly %d rows) so program_trial_count "
                  "rises to %d." % (FUNDING_TRIALS, CUMULATIVE_TRIALS),
        "net_of_cost": True,
        "tests": ["DSR (deflated Sharpe, Bailey-LdP)", "PBO via CSCV (Bailey-Borwein-LdP-Zhu)",
                  "MinTRL", "purge+embargo", "both-halves", "regime conditioning 2024/2025",
                  "noise battery"],
        "cscv_blocks_S": 16,
        "embargo_settlements": max(LOOKBACKS),   # >= deepest trailing-mean lookback (270)
        "both_halves_split": "chronological midpoint of the per-symbol 8h series; "
                             "H1 ~2024-01..2025-03, H2 ~2025-03..2026-06; both on excess_t.",
        "regime_conditioning": "Excess-over-B&H reported separately for calendar 2024, 2025, "
            "2026-partial. A config positive in only one calendar year = single_regime, "
            "not DEPLOY.",
        "noise_battery": "Block-bootstrapped synthetic prices with demeaned returns; the "
            "funding strategy run on them must yield 0 null survivors (GREEN). If any "
            "synthetic null clears DSR>0.95, HALT -- the engine broke -- do not report a pass.",
        "thresholds": {
            "DSR_BAR": 0.95,
            "PBO_BAR": 0.50,
            "MinTRL_rule": "min_trl <= T_effective (per-config bars after warmup)",
            "DEPLOY": "PBO_corpus<0.50 AND noise GREEN AND exists config with: both halves "
                "excess>0 (beats B&H in both) AND excess_sr_bar>0 AND DSR(excess,n=3490)>0.95 "
                "AND MinTRL<=T AND NOT single-symbol AND NOT single-regime.",
            "HOLD_CONDITIONAL": "A config clears DSR(excess)>0.95 and beats B&H both halves "
                "but is single-symbol OR single-regime, OR only the basket clears while "
                "per-symbol evidence is thin. Surfaced for human call; never auto-DEPLOY.",
            "REJECT": "No config clears DSR(excess)>0.95, OR any config fails both-halves-vs-"
                "B&H, OR PBO_corpus>=0.50, OR noise battery not GREEN. => funding axis closed "
                "with a clean, rigorous null; 'every axis tested honestly' becomes true.",
        },
        "verdict_output": "logs/funding_verdict_signed.json, schema referee.verdict/1, "
                          "seeded with this prereg seed, same signed schema as the corpus run.",
    },

    "stop_and_ask": [
        "If clearing the base rate cleanly appears to need MORE than this capped 9-config "
        "grid, do NOT widen it silently -- surface the tension and let the human decide.",
        "If B&H over this window looks unbeatable up front, the null is declared a finding "
        "(already flagged in benchmark.prior_warning).",
        "If closing a gap requires touching cost-model defaults, surface the change first.",
        "If the noise battery flips green->passing at any point, HALT; the engine broke.",
        "If effective-trials diverges hard from raw 3490, show both with reasoning pre-verdict.",
    ],

    "out_of_scope": ["no execution / broker / order path", "no marketplace / signals / mockData",
                     "no ML yet (meta-labeling stays conditional on a SURVIVING primary)",
                     "do not re-touch or re-litigate the dead price corpus"],
}


def sign(rec, seed):
    payload = json.dumps(rec, sort_keys=True, default=float).encode()
    return hashlib.sha256(seed.encode() + payload).hexdigest()


prereg["_sig"] = sign(prereg, SEED)
out = "/home/signal/app/logs/funding_prereg.json"
with open(out, "w") as f:
    json.dump(prereg, f, indent=2)
print(json.dumps(prereg, indent=2))
print("\nwrote", out, "  sig", prereg["_sig"][:16], "...")
