-- Step 15: 1-minute OHLCV continuous aggregate built from trades.
--
-- This is the canonical source of 1-minute bars for the entire platform.
-- All higher-resolution bars (5m, 15m, 1h, 4h, 1d) in subsequent migrations
-- cascade from this aggregate, not from raw trades.
--
-- The view auto-refreshes every minute, computing only buckets affected
-- by new data since the last refresh. Existing trades are backfilled
-- the moment the view is created.
--
-- Columns:
--   instrument_id  — FK target of trades.instrument_id
--   bucket         — bar's open timestamp, aligned to minute boundary
--   open           — first trade price in bucket (by ts)
--   high           — max price in bucket
--   low            — min price in bucket
--   close          — last trade price in bucket (by ts)
--   volume         — sum of trade quantities
--   trade_count    — number of trades in bucket
--   vwap           — volume-weighted average price; numerator/denominator pre-stored
--                    so cascading aggregations to coarser resolutions still
--                    yield correct VWAP.

-- ============================================================
-- The continuous aggregate
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('1 minute'::interval, ts) AS bucket,
    first(price, ts)                       AS open,
    max(price)                             AS high,
    min(price)                             AS low,
    last(price, ts)                        AS close,
    sum(quantity)                          AS volume,
    count(*)                               AS trade_count,
    -- VWAP components kept separately so 5m/1h/etc. aggregates can sum them
    -- and divide at the end. Storing only the ratio loses that capability.
    sum(price * quantity)                  AS price_volume_sum,
    sum(quantity)                          AS volume_for_vwap
FROM trades
GROUP BY instrument_id, bucket
WITH NO DATA;
-- WITH NO DATA: skip immediate backfill. We invoke refresh_continuous_aggregate
-- below for full control of the time window.

-- ============================================================
-- Backfill all existing trade data
-- ============================================================
-- Refreshes from the dawn of time to NOW. With ~3M quotes and ~10K trades,
-- this runs in seconds.
CALL refresh_continuous_aggregate('cagg_bars_1m', NULL, NULL);

-- ============================================================
-- Refresh policy: keep the aggregate fresh going forward
-- ============================================================
-- Refresh once per minute, computing buckets from 5 minutes ago up to 1 minute ago.
-- The 1-minute lag prevents refreshing the in-progress (current) bucket; that
-- bucket is still served by the real-time view from raw trades data.
--
-- start_offset = 5 minutes ensures late-arriving trades within a 5-minute
-- window still get incorporated.
SELECT add_continuous_aggregate_policy(
    'cagg_bars_1m',
    start_offset => INTERVAL '5 minutes',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);

-- ============================================================
-- Indexes for query performance
-- ============================================================
-- Primary query pattern: WHERE instrument_id = ? AND bucket BETWEEN ? AND ?
-- TimescaleDB creates a default index on (bucket DESC) automatically. We add
-- (instrument_id, bucket DESC) so symbol-specific time-range queries don't
-- need a filter pass.
CREATE INDEX IF NOT EXISTS idx_cagg_bars_1m_instrument_bucket
    ON cagg_bars_1m (instrument_id, bucket DESC);


-- ============================================================
-- Sanity-check view: convenience for psql queries
-- ============================================================
-- A regular view that joins bars to instruments for human-readable queries.
-- Phase 2 API endpoints will use parameterized queries, not this view.
CREATE OR REPLACE VIEW bars_1m_view AS
SELECT
    i.canonical_symbol,
    i.venue,
    b.bucket,
    b.open,
    b.high,
    b.low,
    b.close,
    b.volume,
    b.trade_count,
    CASE
        WHEN b.volume_for_vwap > 0 THEN b.price_volume_sum / b.volume_for_vwap
        ELSE NULL
    END AS vwap
FROM cagg_bars_1m b
JOIN instruments i ON i.id = b.instrument_id;
