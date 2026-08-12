-- 0027_user_strategy_name_partial_unique.sql
-- ============================================================
-- Let a deleted strategy's name be reused.
--
-- Deleting a strategy is a SOFT delete (is_active = false; the row stays). But
-- the uniqueness of (user_id, name) was enforced by a plain UNIQUE constraint
-- that ignored is_active, so re-creating a strategy with the name of one you'd
-- deleted hit the constraint and 500'd (the create endpoint's pre-check only
-- looks at active rows, so it didn't catch it first).
--
-- Replace the constraint with a PARTIAL unique index that only applies to ACTIVE
-- strategies. Soft-deleted rows no longer reserve the name.
--
-- Idempotent.
-- ============================================================

ALTER TABLE user_strategies
    DROP CONSTRAINT IF EXISTS user_strategies_user_id_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS user_strategies_user_id_name_active_key
    ON user_strategies (user_id, name)
    WHERE is_active;
