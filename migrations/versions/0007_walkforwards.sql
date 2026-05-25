-- 0007_walkforwards.sql
-- Walk-forward analysis storage.
--
-- One row per walkforward job. Window-level details are stored as a JSONB
-- array on the same row rather than a separate table — small N (typically
-- 5-20 windows per job), and we always query them together with the parent.

CREATE TABLE IF NOT EXISTS walkforwards (
    id                 UUID PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Job configuration (immutable after creation)
    strategy_name      TEXT NOT NULL,
    symbols            TEXT[] NOT NULL,
    bar_resolution     TEXT NOT NULL,
    starting_cash      NUMERIC(28, 12) NOT NULL,
    fee_rate_bps       INTEGER NOT NULL,
    slippage_bps       INTEGER NOT NULL,
    param_grid         JSONB NOT NULL,
    train_bars         INTEGER NOT NULL,
    test_bars          INTEGER NOT NULL,
    num_windows        INTEGER NOT NULL,
    selection_metric   TEXT NOT NULL DEFAULT 'sharpe',

    -- Status & lifecycle
    status             TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    completed_at       TIMESTAMPTZ,
    duration_seconds   NUMERIC(20, 6),
    error_message      TEXT,

    -- Results (NULL until completed)
    total_combos          INTEGER,
    total_backtests_run   INTEGER,
    windows_result        JSONB,              -- array of WindowResult objects

    -- Aggregate test-segment metrics (NULL until completed)
    avg_train_sharpe        NUMERIC(20, 8),
    avg_test_sharpe         NUMERIC(20, 8),
    avg_test_return_pct     NUMERIC(20, 8),
    overfit_drop            NUMERIC(20, 8),   -- avg_train_sharpe - avg_test_sharpe
    win_rate_windows_pct    NUMERIC(20, 8)    -- % of windows where test return > 0
);

CREATE INDEX IF NOT EXISTS idx_walkforwards_user_created
    ON walkforwards (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_walkforwards_status
    ON walkforwards (status)
    WHERE status IN ('pending', 'running');
