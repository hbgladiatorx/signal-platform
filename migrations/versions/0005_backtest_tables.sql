-- Migration 0005: Backtest persistence tables.
--
-- Three new tables:
--   backtests            — one row per backtest run, with denormalized summary metrics
--   backtest_trades      — one row per closed round trip
--   backtest_equity_points — one row per equity-curve sample (per bar in the backtest)
--
-- All three are linked by backtest_id with ON DELETE CASCADE so removing a
-- backtest cleans up its trades and equity points automatically.
--
-- Denormalization rationale: list views like "show me my recent backtests"
-- read just the backtests row. Detail views additionally join trades and
-- equity_points. Storing the summary metrics on the parent row keeps the
-- list view a single index lookup.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- backtests
-- ============================================================
CREATE TABLE IF NOT EXISTS backtests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Configuration
    strategy_name TEXT NOT NULL,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    symbols TEXT[] NOT NULL,
    bar_resolution TEXT NOT NULL,
    bars_start TIMESTAMPTZ,
    bars_end TIMESTAMPTZ,
    num_bars INTEGER,
    starting_cash NUMERIC NOT NULL,
    fee_rate_bps INTEGER NOT NULL DEFAULT 10,
    slippage_bps INTEGER NOT NULL DEFAULT 5,

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds NUMERIC,

    -- Summary metrics (denormalized for fast list queries)
    total_return_pct NUMERIC,
    annualized_return_pct NUMERIC,
    sharpe_ratio NUMERIC,
    sortino_ratio NUMERIC,
    max_drawdown_pct NUMERIC,
    calmar_ratio NUMERIC,
    num_closed_trades INTEGER,
    num_open_trades INTEGER,
    win_rate_pct NUMERIC,
    profit_factor NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_backtests_user_created
    ON backtests (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backtests_org_created
    ON backtests (organization_id, created_at DESC);

-- Partial index: pending/running backtests are the only ones the worker cares about.
CREATE INDEX IF NOT EXISTS idx_backtests_active_status
    ON backtests (status, created_at)
    WHERE status IN ('pending', 'running');


-- ============================================================
-- backtest_trades — closed round trips
-- ============================================================
CREATE TABLE IF NOT EXISTS backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    backtest_id UUID NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_ts TIMESTAMPTZ NOT NULL,
    exit_ts TIMESTAMPTZ NOT NULL,
    entry_avg_price NUMERIC NOT NULL,
    exit_avg_price NUMERIC NOT NULL,
    quantity NUMERIC NOT NULL,
    gross_pnl NUMERIC NOT NULL,
    fees NUMERIC NOT NULL,
    net_pnl NUMERIC NOT NULL,
    duration_seconds NUMERIC NOT NULL,
    num_fills INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_backtest
    ON backtest_trades (backtest_id, exit_ts);


-- ============================================================
-- backtest_equity_points — equity curve samples
-- ============================================================
-- One row per (backtest, bar). For 1h bars over 90 days that's 2160 rows
-- per backtest. We expect O(thousands) of backtests across the platform's
-- lifetime → millions of rows. Composite PK with backtest_id first gives
-- efficient lookups since queries always filter by backtest_id.
--
-- Not a TimescaleDB hypertable: queries never aggregate across backtests,
-- so chunking by time buys nothing.

CREATE TABLE IF NOT EXISTS backtest_equity_points (
    backtest_id UUID NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    cash NUMERIC NOT NULL,
    positions_value NUMERIC NOT NULL,
    total_equity NUMERIC NOT NULL,
    PRIMARY KEY (backtest_id, ts)
);
