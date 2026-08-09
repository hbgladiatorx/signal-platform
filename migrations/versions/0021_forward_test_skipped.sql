-- 0021_forward_test_skipped.sql
-- ============================================================
-- Records an explicit, honest "skip forward testing" choice on a strategy.
--
-- The pipeline is draft -> backtested -> oos_passed -> forward -> deployable.
-- Forward testing (a paper session) is the normal path to `deployable`. A user
-- may instead choose to advance a VALIDATED (oos_passed) strategy toward
-- deployable WITHOUT forward testing — e.g. when the broker/forward path isn't
-- healthy. That choice must be visible and recorded, never a silent bypass and
-- never recorded as if forward testing passed.
--
-- `forward_test_skipped_at` is a durable lifecycle milestone (same convention as
-- promoted_at / deployed_live_at in 0019). When set, compute_strategy_state
-- surfaces forward_test = "skipped" while forward_started stays false, so anyone
-- reading the state knows it advanced without forward-test evidence.
--
-- Nullable; default behaviour (forward testing) is unchanged. Idempotent.
-- ============================================================

ALTER TABLE user_strategies
    ADD COLUMN IF NOT EXISTS forward_test_skipped_at TIMESTAMPTZ;

COMMENT ON COLUMN user_strategies.forward_test_skipped_at IS
    'When the user explicitly skipped forward testing to advance toward deployable. Recorded as skipped (never as passed); default path is unchanged.';
