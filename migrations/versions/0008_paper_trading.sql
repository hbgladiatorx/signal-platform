-- Migration 0008: Live paper-trading tables.
--
-- The paper_trader service runs a strategy live against the bars:closed stream
-- and routes orders to a user's Alpaca *paper* account. These tables persist
-- the session lifecycle, every order/fill, the current position ledger, and an
-- equity curve — mirroring the backtest_* tables so the same UI components can
-- render live results.
--
-- Tables:
--   paper_sessions       — one row per live run, with denormalized summary +
--                          runner restart state (watermark, strategy_state).
--   paper_orders         — one row per order the strategy submitted.
--   paper_fills          — one row per (partial) fill from Alpaca trade_updates.
--   paper_positions      — current event-sourced position ledger per symbol.
--   paper_equity_points  — equity-curve samples (mirrors backtest_equity_points).
--
-- Everything cascades from paper_sessions so deleting a session cleans up.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- paper_sessions
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- Which Alpaca credential (in api_credentials) this session trades with.
    api_credential_id UUID NOT NULL REFERENCES api_credentials(id),

    -- Configuration (immutable after creation)
    strategy_name TEXT NOT NULL,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    symbols TEXT[] NOT NULL,
    asset_class TEXT NOT NULL
        CHECK (asset_class IN ('crypto_spot', 'equity', 'option')),
    bar_resolution TEXT NOT NULL,
    starting_cash NUMERIC NOT NULL,
    max_order_notional NUMERIC,            -- per-order sanity cap; NULL = unlimited
    cancel_open_on_stop BOOLEAN NOT NULL DEFAULT TRUE,

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'starting'
        CHECK (status IN ('starting', 'running', 'stopping', 'stopped', 'error')),
    initialized BOOLEAN NOT NULL DEFAULT FALSE,   -- on_init() guard (once, not on resume)
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,

    -- Live-runner restart state (effectively-once processing)
    last_processed_bar_ts TIMESTAMPTZ,
    last_bar_count INTEGER NOT NULL DEFAULT 0,
    strategy_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Denormalized summary (for fast list views)
    current_equity NUMERIC,
    realized_pnl NUMERIC,
    num_orders INTEGER NOT NULL DEFAULT 0,
    num_fills INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_paper_sessions_user_created
    ON paper_sessions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_sessions_org_created
    ON paper_sessions (org_id, created_at DESC);

-- Partial index: the runner only resumes/owns sessions in an active state.
CREATE INDEX IF NOT EXISTS idx_paper_sessions_active_status
    ON paper_sessions (status, created_at)
    WHERE status IN ('starting', 'running', 'stopping');


-- ============================================================
-- paper_orders
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES paper_sessions(id) ON DELETE CASCADE,

    -- Deterministic, namespaced id (pt_{session8}_{bar_count}_{seq}); UNIQUE so a
    -- redelivered bar that re-submits collides and is treated as idempotent.
    client_order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT,                  -- Alpaca order id; NULL until accepted

    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    quantity NUMERIC NOT NULL,
    limit_price NUMERIC,
    time_in_force TEXT NOT NULL,
    bar_count INTEGER NOT NULL,            -- session bar index that produced it
    expires_at_bar_count INTEGER,         -- bar-count expiry (enforced by runner)

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'partially_filled', 'filled',
                          'canceled', 'expired', 'rejected', 'error')),
    filled_quantity NUMERIC NOT NULL DEFAULT 0,
    avg_fill_price NUMERIC,
    error_message TEXT,

    submitted_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_paper_orders_session_created
    ON paper_orders (session_id, created_at);

-- Pending-order rebuild on runner resume.
CREATE INDEX IF NOT EXISTS idx_paper_orders_open
    ON paper_orders (session_id, status)
    WHERE status IN ('pending', 'accepted', 'partially_filled');


-- ============================================================
-- paper_fills
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_fills (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES paper_sessions(id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES paper_orders(id) ON DELETE CASCADE,
    broker_fill_id TEXT,                   -- Alpaca execution id, if provided
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC NOT NULL,             -- this fill's delta qty
    price NUMERIC NOT NULL,
    fee NUMERIC NOT NULL DEFAULT 0,
    filled_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Dedup partial-fill WS redelivery.
    UNIQUE (order_id, broker_fill_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_fills_session
    ON paper_fills (session_id, filled_ts);


-- ============================================================
-- paper_positions — current event-sourced ledger, one row per open symbol
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_positions (
    session_id UUID NOT NULL REFERENCES paper_sessions(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    avg_cost NUMERIC NOT NULL DEFAULT 0,
    realized_pnl NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, symbol)
);


-- ============================================================
-- paper_equity_points — equity curve samples (mirrors backtest_equity_points)
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_equity_points (
    session_id UUID NOT NULL REFERENCES paper_sessions(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    cash NUMERIC NOT NULL,
    positions_value NUMERIC NOT NULL,
    total_equity NUMERIC NOT NULL,
    PRIMARY KEY (session_id, ts)
);
