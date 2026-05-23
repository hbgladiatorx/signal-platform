-- Step 16: Higher-resolution OHLCV continuous aggregates.
--
-- Each resolution is built FROM cagg_bars_1m (the Step 15 aggregate),
-- not from the trades table. This means each refresh scans only the
-- relevant 1m bars instead of millions of raw trades.
--
-- All resolutions are independent (no cascading chain). If 1d lags, 1h
-- isn't affected.
--
-- Refresh schedules are tuned to each resolution's natural frequency:
--   5m  — every  1 minute,  materialize  5..15 min ago
--   15m — every  5 minutes, materialize 15..45 min ago
--   1h  — every 15 minutes, materialize 1..3   hr  ago
--   4h  — every  1 hour,    materialize 4..12  hr  ago
--   1d  — every  1 hour,    materialize 1..3   day ago
--
-- VWAP is preserved across resolutions by carrying its numerator/denominator
-- as separate columns; query-time view divides them.


-- ============================================================
-- Helper macro: shared OHLCV+VWAP aggregation pattern
-- (PostgreSQL doesn't support actual macros; this comment documents
--  the shape of each cagg.)
-- ============================================================
-- For each resolution R:
--   CREATE MATERIALIZED VIEW cagg_bars_R
--   WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
--   SELECT
--       instrument_id,
--       time_bucket('R'::interval, bucket) AS bucket,
--       first(open, bucket)  AS open,
--       max(high)            AS high,
--       min(low)             AS low,
--       last(close, bucket)  AS close,
--       sum(volume)          AS volume,
--       sum(trade_count)     AS trade_count,
--       sum(price_volume_sum) AS price_volume_sum,
--       sum(volume_for_vwap)  AS volume_for_vwap
--   FROM cagg_bars_1m
--   GROUP BY instrument_id, time_bucket('R'::interval, bucket)
--   WITH NO DATA;


-- ============================================================
-- 5-MINUTE BARS
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_5m
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('5 minutes'::interval, bucket) AS bucket,
    first(open, bucket)   AS open,
    max(high)             AS high,
    min(low)              AS low,
    last(close, bucket)   AS close,
    sum(volume)           AS volume,
    sum(trade_count)      AS trade_count,
    sum(price_volume_sum) AS price_volume_sum,
    sum(volume_for_vwap)  AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('5 minutes'::interval, bucket)
WITH NO DATA;

CALL refresh_continuous_aggregate('cagg_bars_5m', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_bars_5m',
    start_offset      => INTERVAL '15 minutes',
    end_offset        => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '1 minute'
);

CREATE INDEX IF NOT EXISTS idx_cagg_bars_5m_instrument_bucket
    ON cagg_bars_5m (instrument_id, bucket DESC);


-- ============================================================
-- 15-MINUTE BARS
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('15 minutes'::interval, bucket) AS bucket,
    first(open, bucket)   AS open,
    max(high)             AS high,
    min(low)              AS low,
    last(close, bucket)   AS close,
    sum(volume)           AS volume,
    sum(trade_count)      AS trade_count,
    sum(price_volume_sum) AS price_volume_sum,
    sum(volume_for_vwap)  AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('15 minutes'::interval, bucket)
WITH NO DATA;

CALL refresh_continuous_aggregate('cagg_bars_15m', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_bars_15m',
    start_offset      => INTERVAL '45 minutes',
    end_offset        => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

CREATE INDEX IF NOT EXISTS idx_cagg_bars_15m_instrument_bucket
    ON cagg_bars_15m (instrument_id, bucket DESC);


-- ============================================================
-- 1-HOUR BARS
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('1 hour'::interval, bucket) AS bucket,
    first(open, bucket)   AS open,
    max(high)             AS high,
    min(low)              AS low,
    last(close, bucket)   AS close,
    sum(volume)           AS volume,
    sum(trade_count)      AS trade_count,
    sum(price_volume_sum) AS price_volume_sum,
    sum(volume_for_vwap)  AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('1 hour'::interval, bucket)
WITH NO DATA;

CALL refresh_continuous_aggregate('cagg_bars_1h', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_bars_1h',
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes'
);

CREATE INDEX IF NOT EXISTS idx_cagg_bars_1h_instrument_bucket
    ON cagg_bars_1h (instrument_id, bucket DESC);


-- ============================================================
-- 4-HOUR BARS
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_4h
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('4 hours'::interval, bucket) AS bucket,
    first(open, bucket)   AS open,
    max(high)             AS high,
    min(low)              AS low,
    last(close, bucket)   AS close,
    sum(volume)           AS volume,
    sum(trade_count)      AS trade_count,
    sum(price_volume_sum) AS price_volume_sum,
    sum(volume_for_vwap)  AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('4 hours'::interval, bucket)
WITH NO DATA;

CALL refresh_continuous_aggregate('cagg_bars_4h', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_bars_4h',
    start_offset      => INTERVAL '12 hours',
    end_offset        => INTERVAL '4 hours',
    schedule_interval => INTERVAL '1 hour'
);

CREATE INDEX IF NOT EXISTS idx_cagg_bars_4h_instrument_bucket
    ON cagg_bars_4h (instrument_id, bucket DESC);


-- ============================================================
-- 1-DAY BARS
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_1d
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    instrument_id,
    time_bucket('1 day'::interval, bucket) AS bucket,
    first(open, bucket)   AS open,
    max(high)             AS high,
    min(low)              AS low,
    last(close, bucket)   AS close,
    sum(volume)           AS volume,
    sum(trade_count)      AS trade_count,
    sum(price_volume_sum) AS price_volume_sum,
    sum(volume_for_vwap)  AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('1 day'::interval, bucket)
WITH NO DATA;

CALL refresh_continuous_aggregate('cagg_bars_1d', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_bars_1d',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour'
);

CREATE INDEX IF NOT EXISTS idx_cagg_bars_1d_instrument_bucket
    ON cagg_bars_1d (instrument_id, bucket DESC);


-- ============================================================
-- Convenience views for psql exploration
-- ============================================================
-- Each view joins to instruments and computes VWAP for display.
-- API code in Step 17 will query the underlying caggs directly with
-- parameterized queries; views here are for human inspection only.

CREATE OR REPLACE VIEW bars_5m_view AS
SELECT i.canonical_symbol, i.venue, b.bucket, b.open, b.high, b.low, b.close,
       b.volume, b.trade_count,
       CASE WHEN b.volume_for_vwap > 0
            THEN b.price_volume_sum / b.volume_for_vwap
            ELSE NULL END AS vwap
FROM cagg_bars_5m b JOIN instruments i ON i.id = b.instrument_id;

CREATE OR REPLACE VIEW bars_15m_view AS
SELECT i.canonical_symbol, i.venue, b.bucket, b.open, b.high, b.low, b.close,
       b.volume, b.trade_count,
       CASE WHEN b.volume_for_vwap > 0
            THEN b.price_volume_sum / b.volume_for_vwap
            ELSE NULL END AS vwap
FROM cagg_bars_15m b JOIN instruments i ON i.id = b.instrument_id;

CREATE OR REPLACE VIEW bars_1h_view AS
SELECT i.canonical_symbol, i.venue, b.bucket, b.open, b.high, b.low, b.close,
       b.volume, b.trade_count,
       CASE WHEN b.volume_for_vwap > 0
            THEN b.price_volume_sum / b.volume_for_vwap
            ELSE NULL END AS vwap
FROM cagg_bars_1h b JOIN instruments i ON i.id = b.instrument_id;

CREATE OR REPLACE VIEW bars_4h_view AS
SELECT i.canonical_symbol, i.venue, b.bucket, b.open, b.high, b.low, b.close,
       b.volume, b.trade_count,
       CASE WHEN b.volume_for_vwap > 0
            THEN b.price_volume_sum / b.volume_for_vwap
            ELSE NULL END AS vwap
FROM cagg_bars_4h b JOIN instruments i ON i.id = b.instrument_id;

CREATE OR REPLACE VIEW bars_1d_view AS
SELECT i.canonical_symbol, i.venue, b.bucket, b.open, b.high, b.low, b.close,
       b.volume, b.trade_count,
       CASE WHEN b.volume_for_vwap > 0
            THEN b.price_volume_sum / b.volume_for_vwap
            ELSE NULL END AS vwap
FROM cagg_bars_1d b JOIN instruments i ON i.id = b.instrument_id;
