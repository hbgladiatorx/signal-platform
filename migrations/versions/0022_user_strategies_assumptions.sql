-- 0020_user_strategies_assumptions.sql
-- ============================================================
-- Persist the build-time assumptions captured when a strategy was created, so
-- they travel with the strategy to every run instead of dying in the one-shot
-- build chat response.
--
-- These are the things the planner/compiler had to INFER or DEFAULT — an
-- inferred timeframe or symbol, a missing exit, and especially the risk
-- default the compiler applied when "risk N%" was ambiguous between
-- position-size and stop-loss. The run result surfaces them so the user sees
-- what was assumed instead of silently shipping it.
--
-- Nullable: hand-written / raw-code strategies have no recorded assumptions.
-- Idempotent.
-- ============================================================

ALTER TABLE user_strategies
    ADD COLUMN IF NOT EXISTS assumptions JSONB;

COMMENT ON COLUMN user_strategies.assumptions IS
    'Build-time assumptions (inferred timeframe/symbol, applied risk default) carried forward to every run and surfaced on the result.';
