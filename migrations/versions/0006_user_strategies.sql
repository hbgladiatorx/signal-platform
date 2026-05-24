-- ============================================================
-- Migration 0006: user_strategies
--
-- Stores user-authored strategy definitions. Each row represents a
-- strategy class that has been validated and is ready to be loaded
-- by the backtest worker.
--
-- Design notes:
-- * source_code: the raw Python module text. The backtest worker
--   compiles this at run time.
-- * params_schema: JSON Schema extracted from the strategy's
--   PARAMS_MODEL by running the source in a restricted exec
--   environment at save time. Stored so the frontend can render
--   the params form without re-executing user code.
-- * class_name: the Strategy subclass to instantiate.
-- * nl_description: the original natural-language description the
--   user wrote (when the strategy was generated via LLM). For
--   directly-pasted source, this is NULL.
-- * (user_id, name) is unique per user.
-- * is_active: soft-delete flag; deleted rows are kept for audit
--   trails and to make orphan backtests still resolvable.
-- ============================================================

CREATE TABLE user_strategies (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id          UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Identity
    name            VARCHAR(100)    NOT NULL,
    description     TEXT,
    nl_description  TEXT,

    -- Code
    class_name      VARCHAR(100)    NOT NULL,
    source_code     TEXT            NOT NULL,
    params_schema   JSONB           NOT NULL,

    -- Lifecycle
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Names must be unique per user (active ones only — soft-deleted
    -- rows don't block reuse of the name)
    UNIQUE (user_id, name)
);

CREATE INDEX idx_user_strategies_user
    ON user_strategies (user_id, is_active, created_at DESC);

CREATE INDEX idx_user_strategies_org
    ON user_strategies (org_id, is_active);

COMMENT ON TABLE user_strategies IS
    'User-authored strategy definitions. Source code is compiled at backtest time by the worker.';
COMMENT ON COLUMN user_strategies.source_code IS
    'Raw Python source. Compiled and executed in a restricted environment.';
COMMENT ON COLUMN user_strategies.params_schema IS
    'JSON Schema extracted from the strategy''s PARAMS_MODEL at save time.';
COMMENT ON COLUMN user_strategies.nl_description IS
    'Natural-language description used to generate this strategy (if applicable).';
