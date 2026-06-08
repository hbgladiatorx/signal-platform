-- 0016_user_strategies_graph.sql
-- ============================================================
-- Store the thebayn visual builder's reactflow graph + asset class on the
-- user_strategy, so the builder can round-trip a strategy it created.
--
-- Source code remains the runnable artifact (resolver/backtest use it); the
-- graph is the editable view. Per the locked plan, graph->code uses the LLM
-- translate path short-term, but the graph itself is persisted here so the
-- builder can reopen and re-edit a saved strategy.
--
-- Both nullable: hand-written / LLM-only / built-in strategies have no graph.
-- Idempotent.
-- ============================================================

ALTER TABLE user_strategies
    ADD COLUMN IF NOT EXISTS graph_json  JSONB,
    ADD COLUMN IF NOT EXISTS asset_class TEXT;
