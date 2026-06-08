-- Migration 0014: Cross-backtest learning store (Phase 4).
--
-- Phase 3 trained a signal-edge model in-sample on a single backtest. Phase 4
-- accumulates the per-trip feature/label rows across *every* backtest into a
-- persistent store, and trains a reusable model over the aggregate.
--
-- Two tables, both scoped by user_id (the platform is single-org but backtests
-- are user-owned, so we never mix one user's trades into another's model):
--
--   ml_training_samples — one row per closed round trip of a completed
--     backtest: its outcome label and the signals active at entry (sparse
--     JSONB: {signal_name: value_or_null}). Re-saving a backtest replaces its
--     rows (delete-by-backtest then insert), so the store is idempotent.
--
--   ml_models — registry of trained signal-edge models, newest-per-strategy
--     wins. model_json is the model_to_dict() blob plus the feature vocabulary
--     it was trained on.
--
-- See packages/ml/store.py and packages/ml/persistence.py.
--
-- Idempotent.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ml_training_samples (
    id              BIGSERIAL PRIMARY KEY,
    backtest_id     UUID NOT NULL REFERENCES backtests(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    strategy_name   TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    entry_ts        TIMESTAMPTZ,
    profitable      BOOLEAN NOT NULL,
    net_pnl         NUMERIC(28,12) NOT NULL,
    -- Sparse map of the signals active at entry -> numeric reading (or null
    -- when the signal carried no value). Absent signals are simply not keys.
    features        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ml_samples_user_strategy
    ON ml_training_samples (user_id, strategy_name);
CREATE INDEX IF NOT EXISTS idx_ml_samples_backtest
    ON ml_training_samples (backtest_id);

CREATE TABLE IF NOT EXISTS ml_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    strategy_name   TEXT NOT NULL,
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_samples       INTEGER NOT NULL,
    n_backtests     INTEGER NOT NULL,
    -- model_to_dict() output plus {"feature_vocabulary": [...signal names...]}.
    model_json      JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ml_models_user_strategy_trained
    ON ml_models (user_id, strategy_name, trained_at DESC);
