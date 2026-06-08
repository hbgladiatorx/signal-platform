-- Migration 0018: Requested backtest date window (in-sample / out-of-sample).
--
-- Until now a backtest always ran over a symbol's full available history, and
-- bars_start/bars_end recorded the ACTUAL span of data the run consumed. There
-- was no way to ask for a bounded window, so the validation pipeline's
-- "out-of-sample" step could not run on held-out data — it just re-ran the
-- identical full-history backtest.
--
-- These two nullable columns carry the REQUESTED window (inclusive bounds). The
-- worker filters each symbol's bars to [window_start, window_end] before
-- running; bars_start/bars_end still record what was actually consumed inside
-- that window. NULL on both = full history (the prior behaviour), so existing
-- rows and the default in-sample backtest are unchanged.
--
-- Idempotent.

ALTER TABLE backtests
    ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS window_end   TIMESTAMPTZ;
