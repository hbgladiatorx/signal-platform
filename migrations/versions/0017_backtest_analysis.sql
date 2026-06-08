-- Migration 0017: Deterministic backtest analysis storage.
--
-- Adds a JSONB column to the backtests table holding the structured analysis
-- produced by packages/analysis/backtest_analysis.py: a verdict, a 0-100
-- quality score, the key metrics used (incl. derived breakeven win rate,
-- payoff ratio, expectancy), and a ranked list of findings — each a concrete
-- "what worked / what to tweak / why / what to fix" item derived arithmetically
-- from attribution_json + ml_model_json + the run's metrics.
--
-- The optional LLM narrative is stored inside this same blob under the
-- "narrative" key (NULL until generated on-demand via the narrative endpoint),
-- so the detail view reads one column. Stored as a derived blob (read whole,
-- never queried by inner fields), mirroring attribution_json (0012) and
-- ml_model_json (0013). NULL for runs completed before this migration.
--
-- Idempotent.

ALTER TABLE backtests
    ADD COLUMN IF NOT EXISTS analysis_json JSONB;
