# Asymmetric Catalyst Breakout — Signal & Backtest System

A signal engine + point-in-time backtester for a discretionary-systematic
equity-and-options strategy that front-runs the **validator**: beaten-down or
overlooked names that re-rate when a credible external party (government capital,
a hyperscaler stake, an AI-demand inflection) injects capital or demand. The
cheapness is the setup; the validation event is the trigger.

Two products, one codebase:

1. **Live signal engine** (Modules 1–5) — a small number of high-conviction
   daily signals with entry, stop, target ladder, and the chosen options wrapper.
2. **Point-in-time backtester** (Module 6) — evaluates the same parameter stack
   historically with **zero lookahead**.

> The single most important property is **point-in-time integrity**. Every
> historical decision uses only data knowable as of its decision date. If any
> module can see future data when making a past decision, the system has failed
> regardless of how good the results look.

---

## Quick start (offline, no API keys)

The PIT layer, anti-bias logic, and backtester run on the Python **stdlib** plus
a local SQLite panel — no network, no credentials.

```bash
# 1. Verify the anti-bias guarantees + run an end-to-end backtest (no pytest needed)
python scripts/verify.py

# 2. Run the live engine against a seeded panel and dump the Section 8 payload
python scripts/demo_live.py

# 3. Full test suite (requires pytest)
pip install -e ".[dev]"      # or: pip install pytest
pytest -q
```

`scripts/verify.py` reproduces every anti-bias test against the real code paths
and prints PASS/FAIL, for environments where pytest cannot be installed.
`scripts/verify_ingest.py` does the same for the ingest transforms + PIT stamping.

## Workflow: backtest on real data, then go live

```bash
# 0. Keys + DB (see .env.example). DATABASE_URL can stay sqlite for a first pass.
export POLYGON_API_KEY=...  FINNHUB_API_KEY=...  SEC_USER_AGENT="you you@example.com"

# 1. BACKFILL the point-in-time panel from the providers (prices/universe/fundamentals/catalysts).
python -m catalyst.ingest.backfill --tickers NOK,DELL,MU,AMD --start 2018-01-01 --end 2024-12-31

# 2. BACKTEST (event-driven: each name is evaluated on its catalyst dates only).
python scripts/run_backtest.py --min-n 20

# 3. Read the per-catalyst / per-regime report. Kill any bucket that fails the
#    Section 11 gates. Only then turn on the options overlay (stage two).

# 4. GO LIVE: run the daily crons (or the Railway schedule).
python -m catalyst.cron.ivrank_snapshot     # builds the IV-rank store forward
python -m catalyst.cron.live_engine          # emits the day's signals
```

> **IV-rank caveat:** historical ATM IV is *not* backfilled (it must be
> reconstructed from per-contract options aggregates — a separate, heavier job).
> The `ivrank_snapshot` cron builds it **forward**, so the options overlay and
> live IV-rank gating warm up over ~60 trading days. The underlying-edge backtest
> does not depend on it.

---

## Architecture

```
config/defaults.py            All CONFIG params (locked, a-priori). Nothing hardcoded inline.
src/catalyst/
  clients/                    Thin provider clients: caching + retry + rate-limit backoff
    polygon, finnhub, edgar, usaspending
  ingest/                     Provider -> panel backfill + knowable_at stamping
    loaders.py (transforms), upsert.py (idempotent writes), backfill.py (CLI),
    chain.py (shared options-chain fetch/normalize for live + backtest)
  store/
    db.py                     SQLite (offline/test) or Supabase Postgres (prod), same SQL
    panel.py                  AsOfPanel -- HARD <= as_of filter on every read (PIT enforcement)
  pit/features.py             MODULE 0: get_pit_features(ticker, as_of) -> FeatureRow
  screen/distressed.py        MODULE 1: distressed-and-viable wide screen -> watchlist
  catalysts/                  MODULE 2: catalyst gate (structured + validator tiers)
  options/                    MODULE 3: IV-rank store + four-quadrant wrapper engine
  signals/                    MODULE 4: entry/exit generator | MODULE 5: live payload + push
  backtest/                   MODULE 6: evaluate_signal, sweep engine, measure, stats, report
  cron/                       Railway entrypoints: live_engine, ivrank_snapshot
  testing/synth.py            Reusable synthetic-panel seeders (pytest-free)
migrations/0001_init.sql      Canonical Postgres DDL (mirrors the sqlite schema)
railway.toml                  Two crons: ivrank-snapshot + live-signal-engine
tests/                        Anti-bias test suite (one file per non-negotiable rule)
scripts/                      verify.py (stdlib harness), demo_live.py
```

### Data flow
`get_pit_features` is the single chokepoint. It reads **only** through
`AsOfPanel`, which appends a `<= as_of` predicate to every query and re-asserts
no future row slipped through. The backtester's `evaluate_signal` confirms on day
`T` using `T`-close-knowable data; the engine then enters at the **`T+1` open**
and applies the do-not-chase rule there, so some signals never fill.

---

## The non-negotiable anti-bias guarantees (Section 10) and where they live

| # | Rule | Enforced in | Test |
|---|------|-------------|------|
| 1 | **No lookahead** | `store/panel.py` (`<= as_of` + `_assert_no_future` guard) | `test_no_lookahead.py` |
| 2 | **Next-bar entry** | `backtest/engine.py` (`entry_lag_bars`, do-not-chase at T+1 open) | `test_next_bar_entry.py` |
| 3 | **Survivorship** | `store/panel.py::universe` (keeps later-delisted names) | `test_survivorship.py` |
| 4 | **PIT fundamentals/catalysts** | filter on `knowable_at`, never `period_end`/`event_date` | `test_pit_fundamentals.py` |
| 5 | **Locked parameters** | `config/defaults.py` (a-priori defaults; tune only via walk-forward) | — |
| 6 | **Archetypes ≠ scorecard** | no archetype literal in the decision path; engine is name-blind | `test_archetype_not_scored.py` |

`min_trades_per_bucket` suppression and catalyst×regime segmentation are checked
in `test_min_n_reporting.py`.

---

## CONFIG parameters and defaults

Every value below is in `config/defaults.py` and overridable via
`CATALYST_<SECTION>_<KEY>` env vars (e.g.
`CATALYST_SCREEN_MARKET_CAP_FLOOR_USD=500000000`). **Defaults are locked** — do
not tune them against the test set (rule #5).

### `screen` — Module 1 (distressed-and-viable)
| Key | Default | Meaning |
|-----|---------|---------|
| `market_cap_floor_usd` | `300_000_000` | Survivability + options exist. |
| `min_drawdown_from_52w_high` | `0.40` | Distressed if drawdown ≥ this … |
| `within_pct_of_52w_low` | `0.25` | … OR within this % of the 52-week low. |
| `min_avg_daily_dollar_volume_usd` | `5_000_000` | Liquidity floor. |
| `adv_lookback_days` | `20` | Window for average daily dollar volume. |
| `viability_lookback_quarters` | `4` | Margin/FCF trend window. |
| `leverage_flag_debt_to_equity` | `2.0` | **Flagged, not excluded** (levered turnarounds in scope). |
| `require_listed_options` | `True` | Optionability gate. |

### `catalyst` — Module 2 (the gate)
| Key | Default | Meaning |
|-----|---------|---------|
| `min_earnings_surprise_pct` | `5.0` | Structured: surprise threshold. |
| `require_guidance_raise_with_surprise` | `True` | Surprise must pair with a guidance raise. |
| `analyst_revision_cluster_n` | `3` | ≥ N upgrades/target raises … |
| `analyst_revision_window_days` | `14` | … within T days. |
| `insider_net_buy_threshold_usd` | `1_000_000` | Net insider buy cluster threshold. |
| `insider_window_days` | `30` | Insider cluster window. |
| `institutional_position_delta_pct` | `1.0` | New large 13F-style position delta. |
| `federal_award_min_usd` | `10_000_000` | Validator: federal contract/grant size. |
| `strategic_stake_min_pct` | `5.0` | Validator: 13D/13G stake threshold. |
| `news_keywords` | stake, investment, award, … | Keyword scan, cross-referenced to an 8-K. |
| `validator_requires_review` | `True` | Validator hits flagged for human bull/bear judgement. |

### `options` — Module 3 (wrapper engine + IV-rank store)
| Key | Default | Meaning |
|-----|---------|---------|
| `iv_rank_window_trading_days` | `252` | Trailing window for the IV-rank percentile. |
| `iv_rank_min_history_days` | `60` | Below this → IV rank **unreliable**, defer sizing to a human. |
| `iv_rank_split_threshold` | `50.0` | ≤ → LEAPS (low/mid IV); > → debit call spread (high IV). |
| `leaps_target_delta_low` / `_high` | `0.60` / `0.70` | LEAPS target delta band. |
| `leaps_min_days_past_catalyst` | `30` | Expiry must land past catalyst resolution. |
| `min_open_interest_per_leg` | `250` | Liquidity gate. |
| `max_bid_ask_pct_of_premium` | `0.15` | Liquidity gate. |
| `min_contract_volume` | `25` | Liquidity gate. |
| `max_premium_at_risk_pct_of_book` | `0.02` | Position sizing for defined-risk structures. |

### `entry_exit` — Module 4
| Key | Default | Meaning |
|-----|---------|---------|
| `atr_period` | `14` | ATR lookback. |
| `base_lookback_days` | `50` | Consolidation low / 50-day base. |
| `do_not_chase_atr_mult` | `2.5` | Reject if price > N ATR above the catalyst trigger. |
| `atr_stop_mult` | `2.0` | ATR-based stop multiple (stop = max of this and base-break). |
| `trim_plan` | `(0.33, 0.33, 0.34)` | Fractions trimmed at T1/T2/T3. |

### `backtest` — Module 6
| Key | Default | Meaning |
|-----|---------|---------|
| `entry_lag_bars` | `1` | **Entry is T+1 open.** Never the signal bar. |
| `forward_horizons_months` | `(3, 6, 12)` | Fixed-horizon return measurement points. |
| `regime_boundaries` | `("2021-01-01", "2023-01-01")` | Pre-2021 / 2021–2022 / AI-era split. |
| `min_trades_per_bucket` | `20` | Report **refuses** to publish stats below this N. |
| `bootstrap_iterations` | `10_000` | Monte-Carlo resamples for expectancy CI. |
| `bootstrap_ci` | `0.95` | Confidence level. |
| `options_bid_ask_haircut` | `0.50` | Fraction of spread paid vs mid (never mid). |
| `illiquid_extra_haircut` | `0.25` | Additional haircut for thin chains. |

### `runtime` — provider clients / persistence
| Key | Default | Meaning |
|-----|---------|---------|
| `cache_ttl_seconds` | `21_600` | Provider cache TTL (6h). |
| `max_retries` | `5` | Retry budget per request. |
| `backoff_base_seconds` / `backoff_max_seconds` | `0.5` / `30.0` | Exponential backoff (honors `Retry-After`). |
| `database_url` | `sqlite:///catalyst.db` | Offline default; set to Supabase Postgres in prod. |
| `*_base_url`, `user_agent` | provider URLs | Endpoint roots; SEC requires a descriptive UA w/ contact. |

`archetype_names = ("INTC","NOK","DELL","MU")` is present in config **only** so
the test suite can assert their absence from the decision path. Signal logic
never reads it (rule #6).

---

## Backtest outputs (Section 9)

`backtest.report.generate(trades)` returns three segmentations, each refusing to
report any bucket under `min_trades_per_bucket`:

- **`by_catalyst`** — never blends a clinical binary, a squeeze, and a government
  re-rate into one statistic.
- **`by_regime`** — pre-2021 vs AI-era reported separately. *If the edge only
  exists post-2023, you found the regime, not the edge.*
- **`by_cell`** — catalyst × regime, the strongest anti-overfit lens.

Each reported bucket carries: fixed-horizon return (does the signal predict?),
rules-based realized P&L (does the system capture it?), and the **capture gap**
between them, plus expectancy, win rate, payoff ratio, profit factor, max
drawdown, Sortino, and a bootstrap CI on expectancy.

**Options overlay is stage two** (`backtest/options_overlay.py`): do not start
with simulated option fills — prove the underlying edge first, then model fills
off historical IV with a bid-ask haircut (never mid) and flag thin-data names.

---

## Kill conditions (Section 11)

A catalyst bucket is **dead** (excluded from the live engine) unless it clears:
≥ 20 trades, positive expectancy after modeled costs/slippage, and persistence
out-of-sample across ≥ 2 regimes. The decisive test is a multi-month **forward
paper run** of the live engine — validator catalysts confirm better forward than
backward. Treat the historical backtest as plumbing validation.

---

## Deployment (Railway + Supabase)

1. Apply `migrations/0001_init.sql` to your Supabase Postgres.
2. Set env vars from `.env.example` (provider keys, `DATABASE_URL`,
   `SIGNAL_WEBHOOK_URL`).
3. `railway.toml` defines two daily crons (UTC): the IV-rank snapshot just after
   the close, then the live signal engine.

> Confirm exact endpoint names and rate limits against each provider's current
> docs before going live — the clients are structured for it but the API
> surfaces drift.

## Status / honest limitations

- The **PIT layer, anti-bias logic, backtester, and ingest transforms are
  functional and verified offline** (`scripts/verify.py` 18/18 +
  `scripts/verify_ingest.py` 19/19 = 37 checks pass).
- The **options chain is now wired** into both the live engine and the backtest
  engine via an injectable `chain_fetcher` (`ingest/chain.py`); with a Polygon
  key the live engine selects LEAPS/spread/common for real, and without one it
  degrades to `COMMON`/`REJECT`.
- The **provider clients + ingest loaders are interface-complete** but the exact
  provider field names / endpoints must be confirmed against current docs before
  a production backfill — `loaders.py` flags this inline. Finnhub's as-reported
  concept tags in particular vary by filer; the extractor is best-effort with
  documented fallbacks.
- No real market data ships with this repo; everything runs on synthetic panels
  for verification.
