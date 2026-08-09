# Bayn Backend Requirements

## What Bayn actually is

Two-sided product on one account:

- **Trader app (`/app/*`)** — subscribes to verified, edge-tested strategies. Receives signals (entry/stop/target + reasoning), tracks personal performance, can fire orders via connected brokerages or an AI agent (MCP). Never holds funds.
- **Studio app (`/studio/*`)** — developers build strategies in a node graph (or AI-described), backtest, forward-test, submit to Bayn for catalog review, and earn revenue share when accepted.
- **Shared** — auth, plans/billing (Stripe), live market data + news (Finnhub), preferences/onboarding state.

Bayn never custodies funds. Execution always happens at the user's brokerage via broker connection or agent (MCP).

---

## 1. Identity & Account

**`auth.users`** (Lovable Cloud / Supabase managed) — email, password, OAuth.

**`profiles`** (1:1 with `auth.users`)
- `user_id` (PK, FK auth.users)
- `display_name`, `avatar_url`
- `timezone`, `currency` (default USD)
- `onboarding_path` enum: `trader | developer | both`
- `default_mode_on_login` enum: `trader | studio | null`
- `onboarded_at`, `created_at`, `updated_at`

**`user_roles`** (separate table, never on profiles) — `admin | reviewer | user` for catalog review.

**`experience_profile`** (1:1)
- `level`: retail | active | professional | institutional
- `years_bucket`, `motivations[]`, `signal_sources[]`

---

## 2. Preferences (replaces localStorage `bayn.prefs.*`)

One row per user per scope. Today everything writes to localStorage via `user-prefs.tsx` — backend must mirror these keys.

**`trader_preferences`**
- enabled_asset_classes[] (stocks/crypto/options/futures)
- watchlist[] (validated tickers)
- news_categories[], news_sources[], news_only_watched bool
- home_layout[], hidden_sections[]
- account_size, risk_per_trade_pct, max_concurrent_positions
- daily_loss_limit `{ enabled, threshold }`
- default_timeframe, default_chart_type
- notifications (jsonb: signalFired/HitTarget/HitStop/weeklySummary/strategyHWM/tickerNews)
- live_tracking_strategy_id

**`studio_preferences`**
- asset_classes[], experience `{ level, used_node_builder, entry }`
- backtest_defaults `{ starting_capital, date_range, commission_model, commission_value, slippage_bps, currency }`
- forward_test_defaults `{ paper_capital, auto_promote_days, delivery{inApp,email,push} }`
- ai_prefs `{ node_style, remember_session }`
- workspace_defaults `{ view, default_asset_class }`

**`onboarding_state`** — `{ step, total, path, completed_at }` for save & resume.

**`dismissed_checklist_items[]`**

---

## 3. Billing & Plans

Stripe-backed. Tier + add-on catalog already coded in `src/lib/api/billing.ts` — keep as the source of truth for SKUs.

**`subscriptions`** (1:1 user)
- trader_tier: `trader-signal | trader-edge | trader-desk | null`
- developer_tier: `studio-builder | studio-quant | studio-principal | null`
- billing_cycle: monthly | annual
- stripe_customer_id, stripe_subscription_id (one per side, or combined)
- status, current_period_end, cancel_at

**`subscription_addons`** — user_id, addon_id, qty, stripe_subscription_item_id.

**`usage_counters`** (monthly rollups for limit enforcement)
- trader_ai_queries, studio_backtest_runs, studio_ai_builds, studio_live_strategies, period_start.

**Webhook route** `/api/public/stripe/webhook` — signature-verified, updates subscriptions/usage.

---

## 4. Strategy Catalog (Trader-facing)

**`strategies`** — Bayn's published catalog (also includes 4 always-free verified ones).
- id, name, slug, description, long_description, entry_rules, exit_rules
- asset_class, symbols[], status (Watching/In Position/Cooldown)
- pipeline_stage (Draft → Published)
- edge_verified bool, is_free bool, published_at
- developer_id (FK profiles), dev_handle (denorm)
- live_since, last_signal_at
- stats (jsonb: sharpe, win_rate, max_dd, sample_size, avg_r, live_days, subscribers)

**`strategy_follows`** — user_id, strategy_id, followed_at. Drives slot counting via `FREE_STRATEGY_IDS`.

**`signals`** — every fire from a published strategy
- id, strategy_id, asset_class, symbol, direction (LONG/SHORT)
- entry, stop, target, status (OPEN/HIT_TARGET/HIT_STOP/EXPIRED)
- fired_at, closed_at, pnl_r
- reasoning text
- options fields: strike, expiry, delta, iv
- futures fields: contract_month, tick_size
- price_series jsonb (or separate `signal_price_points` table)

**`taken_signals`** — user_id, signal_id, taken_at, fill_price, outcome, pnl_r. Powers `/app/performance`.

**`user_equity_points`** — user_id, t, equity (computed from taken_signals; can be a view).

---

## 5. Studio (Developer-facing)

**`dev_strategies`** — developer drafts
- id, user_id, name, description, asset_class
- stage (Draft/Backtested/OOS Passed/Forward Testing/Live/Submitted/Under Review/Published/Rejected)
- graph jsonb `{ nodes[], edges[] }` (current revision)
- live_since_days, stats jsonb, created_at, last_run_at

**`dev_strategy_versions`** — id, dev_strategy_id, graph jsonb, note, created_at. Append-only history.

**`backtest_runs`**
- id, dev_strategy_id, user_id, ran_at
- params `{ start_date, end_date, capital, commission_bps, slippage_bps }`
- stats `{ total_return, cagr, sharpe, sortino, max_dd, win_rate, profit_factor, avg_win/loss/hold_days, total_trades }`
- equity jsonb[], monthly_returns jsonb[]
- compute_status: queued/running/done/failed

**`backtest_trades`** — id, backtest_run_id, entry/exit_date, symbol, direction, entry, exit, pnl_pct, pnl_r.

**`forward_tests`** — id, dev_strategy_id, paper_capital, started_at, auto_promote_days, status.

**`personal_signals`** — same shape as `signals` but tied to a dev_strategy + owning user. Fed back to that developer's `/studio/signals` and (if subscribed) their trader feed.

**`strategy_submissions`** — dev_strategy_id, submitted_at, submission_status (Submitted/Under Review/Pipeline Validation/Human Review/Accepted/Rejected), reviewer_user_id, notes, decided_at. On Accepted → row appears in `strategies` (catalog).

**`studio_earnings`** — month, dev_strategy_id, user_id (developer), amount, subscribers. Driven by `strategy_follows` × revenue-share rate per tier (Quant/Principal).

---

## 6. Connections (Brokers + AI Agent)

**`broker_connections`** — user_id, broker_id (coinbase/ibkr/tradier/topstepx/robinhood-agentic), status (pending/connected/error), oauth tokens encrypted, connected_at. Per `BrokerId` enum already defined.

**`broker_defaults`** — user_id, asset_class → broker_id.

**`agent_setup`** (1:1 user)
- platform (claude-code/claude-desktop/chatgpt/codex/cursor/other)
- bayn_mcp_connected, brokerage_agent_connected, read_signal_feed bools
- mcp_api_key (server-issued, used by external agent to authenticate to Bayn MCP)

**MCP server route** at `agent.bayn.app/mcp` — exposes signal feed + order intent endpoints. Authenticated by per-user mcp_api_key.

---

## 7. Notifications & Delivery

**`notification_events`** — user_id, type (signal_fired/hit_target/hit_stop/weekly_summary/strategy_hwm/ticker_news), payload jsonb, delivered_at, channel (in_app/email/push).

**`device_tokens`** — for push (if/when added).

**Email delivery** via Lovable email connector or Resend. Templates: welcome, signal alerts, weekly summary, submission decision.

---

## 8. Market Data & News (already partially live)

Server functions in `src/lib/api/finnhub.functions.ts` — keep as-is. The backend stores **no candle/quote data** — Finnhub is queried on demand with a 60s in-memory cache.

What does need persisting:
- **`ticker_metadata`** cache: symbol, description, exchange, asset_class, last_validated_at. Avoids re-hitting Finnhub `/search` for known symbols and lets server-side strategy execution know what each symbol is.

---

## 9. Server-side jobs (cron / queue)

Public webhook/cron routes under `/api/public/*`:

- **Signal firing engine** — runs every minute, evaluates each Published strategy's rules against live market data, inserts into `signals`, fans out notifications.
- **Forward-test runner** — same engine in paper mode, writes to `personal_signals`.
- **Backtest worker** — consumes `backtest_runs` where status=queued. Heavy compute — likely needs an external worker, not the Worker runtime. Returns results into `backtest_runs` + `backtest_trades`.
- **Weekly summary** — Sunday cron → notification_events.
- **Stripe webhook** — subscription state sync.
- **Earnings rollup** — monthly cron computing `studio_earnings` from active subscribers × tier rev-share.

---

## 10. Security (RLS)

Every user-scoped table: `user_id = auth.uid()` policies.
`user_roles` checked via `public.has_role()` security-definer function.
Reviewers (`has_role('reviewer')`) can read `strategy_submissions` + parent `dev_strategies` for queue work.
Catalog `strategies` is publicly readable (no PII).
`backtest_runs`, `dev_strategies`, `personal_signals`, `taken_signals`, `notification_events`, `broker_connections`, `agent_setup`, all preferences: owner-only.

---

## What I'm NOT covering here

- Actual backtest engine implementation (math + data licensing — separate decision).
- Broker OAuth specifics per broker (per-vendor work).
- Revenue-share % per tier (business decision — table just stores the amount).
- Email/push provider choice.

---

## Suggested build order

1. Enable Lovable Cloud → `profiles`, `user_roles`, preferences tables, onboarding_state. Migrate `user-prefs.tsx` reads/writes.
2. `subscriptions` + Stripe webhook + `usage_counters`. Replace `billing.ts` mock storage.
3. `strategies` + `strategy_follows` + seed the 4 free strategies as real rows.
4. `signals` + `taken_signals` + `notification_events` (signal firing can stay stubbed until rule engine exists).
5. Studio: `dev_strategies` + versions + `backtest_runs` (queue stub) + `strategy_submissions`.
6. `broker_connections` + `agent_setup` + MCP route.
7. Cron jobs (weekly summary → earnings rollup → signal engine last).
