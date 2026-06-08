-- Migration 0009: Seed a couple of US-equity instruments (paper trading Stage 2).
--
-- The ingestion_alpaca service publishes trades for these canonical symbols;
-- persistence_worker and the bar caggs resolve canonical_symbol -> instrument_id,
-- so equity instruments must exist before equity bars can be built/queried.
--
-- These are starter rows; add more via the Settings → Instruments UI. Idempotent.

INSERT INTO instruments (asset_class, canonical_symbol, venue, native_symbol, base, quote, metadata)
VALUES
    ('equity', 'AAPL@ALPACA', 'ALPACA', 'AAPL', 'AAPL', 'USD', '{"name": "Apple Inc."}'),
    ('equity', 'SPY@ALPACA',  'ALPACA', 'SPY',  'SPY',  'USD', '{"name": "SPDR S&P 500 ETF"}')
ON CONFLICT (canonical_symbol) DO NOTHING;
