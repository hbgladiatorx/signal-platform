-- Migration 0012: Performance attribution storage.
--
-- Adds a single JSONB column to the existing backtests table holding the
-- attribution decomposition computed at completion (the "why" behind a run):
-- per-symbol and per-signal P&L, win rates, share of total, and signal
-- fire/block frequency. Stored as a derived blob rather than normalized
-- tables because it is read whole on the detail view and never queried by
-- its inner fields. NULL for runs completed before this migration and for
-- runs that produced no closed trades.
--
-- See packages/backtest/attribution.py (compute_attribution / attribution_to_dict).
--
-- Idempotent.

ALTER TABLE backtests
    ADD COLUMN IF NOT EXISTS attribution_json JSONB;
