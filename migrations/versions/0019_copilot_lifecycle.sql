-- ============================================================
-- Migration 0019: copilot lifecycle milestones + bayn submissions
--
-- The Bayn Copilot drives a strategy through a 6-stage pipeline:
--   draft -> backtested -> oos_passed -> forward -> deployable -> bayn_eligible
--
-- The first four stages are DERIVED at read time from real artifacts
-- (completed backtests, walk-forwards, paper sessions) — no columns needed.
-- The last two are gated transitions that require explicit user confirmation,
-- so they are STORED here as durable milestones:
--   * promoted_at        — user promoted a forward-tested strategy to deployable
--   * deployed_live_at    — a live (real-money) deploy happened -> bayn_eligible
--   * submitted_to_bayn_at — strategy was submitted to the desk for review
--
-- last_deploy_mode / last_deployed_at record the most recent deploy of either
-- mode (paper or live) for display; they do not gate anything.
-- ============================================================

ALTER TABLE user_strategies
    ADD COLUMN IF NOT EXISTS promoted_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deployed_live_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_deploy_mode    VARCHAR(10),
    ADD COLUMN IF NOT EXISTS last_deployed_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_to_bayn_at TIMESTAMPTZ;

COMMENT ON COLUMN user_strategies.promoted_at IS
    'When the user promoted this strategy to deployable (gated, requires confirmation).';
COMMENT ON COLUMN user_strategies.deployed_live_at IS
    'When this strategy was first deployed live (real money) — advances stage to bayn_eligible.';
COMMENT ON COLUMN user_strategies.submitted_to_bayn_at IS
    'When this strategy was submitted to the Bayn desk for review.';


-- ============================================================
-- bayn_submissions: a strategy submitted to the desk for review.
-- One row per submission; a strategy may be re-submitted after changes.
-- ============================================================
CREATE TABLE IF NOT EXISTS bayn_submissions (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id        UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    strategy_id   UUID         NOT NULL REFERENCES user_strategies(id) ON DELETE CASCADE,
    strategy_name VARCHAR(100) NOT NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending_review',
    note          TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    reviewed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bayn_submissions_user
    ON bayn_submissions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bayn_submissions_strategy
    ON bayn_submissions (strategy_id, created_at DESC);

COMMENT ON TABLE bayn_submissions IS
    'Strategies submitted to the Bayn desk for review. Backs the copilot submit_to_bayn tool.';
