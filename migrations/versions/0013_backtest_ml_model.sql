-- Migration 0013: Signal-edge ML model storage (Phase 3).
--
-- Adds a JSONB column to the backtests table holding the per-run signal-edge
-- model: the in-sample logistic-regression fit over the feature/label store
-- (which signals predict profitable trades), its accuracy/log-loss, learned
-- feature weights, and per-signal empirical/predicted edge. Stored as a
-- derived blob (read whole on the detail view, never queried by inner fields),
-- mirroring attribution_json from migration 0012. NULL for runs completed
-- before this migration and for runs with nothing to learn (no signals or no
-- closed trades).
--
-- See packages/ml/model.py (train_signal_edge_model / model_to_dict).
--
-- Idempotent.

ALTER TABLE backtests
    ADD COLUMN IF NOT EXISTS ml_model_json JSONB;
