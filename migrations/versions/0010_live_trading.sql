-- Migration 0010: Real-money live trading (Binance.US).
--
-- The live-trading runtime (services/paper_trader + packages/livetrade) was
-- built for Alpaca *paper* accounts. This migration extends the existing
-- paper_* tables to also carry REAL-MONEY sessions routed to a venue's live
-- exchange (Binance.US spot, which has no paper sandbox).
--
-- Rather than fork a parallel live_* schema, we add a `mode` discriminator:
--   mode = 'paper'  → simulated funds (Alpaca paper). Default; pre-existing rows.
--   mode = 'live'   → REAL money on a real exchange. Order submission is gated
--                     by the global kill-switch and a per-session daily-loss halt.
--
-- New columns:
--   paper_sessions.mode           — 'paper' | 'live'  (existing rows default 'paper')
--   paper_sessions.max_daily_loss — live guardrail: halt the session when the
--                                   day's equity drawdown exceeds this (NULL = off).

ALTER TABLE paper_sessions
    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'paper'
        CHECK (mode IN ('paper', 'live'));

ALTER TABLE paper_sessions
    ADD COLUMN IF NOT EXISTS max_daily_loss NUMERIC;  -- live drawdown halt; NULL = off

COMMENT ON COLUMN paper_sessions.mode IS
    'paper = simulated (Alpaca paper); live = REAL money on a real exchange.';
COMMENT ON COLUMN paper_sessions.max_daily_loss IS
    'Live guardrail (USD): auto-halt the session when intraday equity drawdown '
    'exceeds this amount. NULL disables the halt.';
