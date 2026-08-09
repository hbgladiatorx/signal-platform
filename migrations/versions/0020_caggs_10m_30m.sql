-- Migration 0020: Add 10m and 30m continuous aggregates.
--
-- Adds two new bar resolutions (10-minute, 30-minute) to the cagg hierarchy so
-- the backtest engine, live runner, and bar_builder can read/serve them. Both
-- roll up directly from cagg_bars_1m (10x / 30x the 1m bucket), exactly like the
-- existing 5m/15m caggs (which also build on cagg_bars_1m).
--
-- Refresh policies cover only the rolling-recent live window (like 5m/15m);
-- historical backfill is materialized manually via CALL refresh_continuous_aggregate
-- over the inserted range (see scripts/backfill_history.py).
--
-- NB: continuous-aggregate DDL cannot run inside a transaction block, so apply
-- each statement standalone (psql -c per statement), not wrapped in BEGIN/COMMIT.

-- 10-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_10m
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('00:10:00'::interval, bucket) AS bucket,
       first(open, bucket)  AS open,
       max(high)            AS high,
       min(low)             AS low,
       last(close, bucket)  AS close,
       sum(volume)          AS volume,
       sum(trade_count)     AS trade_count,
       sum(price_volume_sum) AS price_volume_sum,
       sum(volume_for_vwap) AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('00:10:00'::interval, bucket)
WITH NO DATA;

SELECT add_continuous_aggregate_policy('cagg_bars_10m',
       start_offset => INTERVAL '30 minutes',
       end_offset   => INTERVAL '10 minutes',
       schedule_interval => INTERVAL '2 minutes',
       if_not_exists => true);

-- 30-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_bars_30m
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('00:30:00'::interval, bucket) AS bucket,
       first(open, bucket)  AS open,
       max(high)            AS high,
       min(low)             AS low,
       last(close, bucket)  AS close,
       sum(volume)          AS volume,
       sum(trade_count)     AS trade_count,
       sum(price_volume_sum) AS price_volume_sum,
       sum(volume_for_vwap) AS volume_for_vwap
FROM cagg_bars_1m
GROUP BY instrument_id, time_bucket('00:30:00'::interval, bucket)
WITH NO DATA;

SELECT add_continuous_aggregate_policy('cagg_bars_30m',
       start_offset => INTERVAL '90 minutes',
       end_offset   => INTERVAL '30 minutes',
       schedule_interval => INTERVAL '5 minutes',
       if_not_exists => true);
