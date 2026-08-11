-- 0026_market_data_retention.sql
-- ============================================================
-- Compression + retention for the raw market-data hypertables.
--
-- `trades` (~13 GB) and `quotes_l1` (~2.3 GB) are raw ticks the platform only
-- uses to BUILD bars in real time; backtests read `bars` (~18 MB, built by
-- bar_builder). No compression or retention policy existed, so they grew
-- unbounded. This:
--   1. enables TimescaleDB native compression on trades / quotes_l1 / bars,
--   2. compresses existing old chunks immediately (the big one-time reclaim —
--      tick data typically compresses 90%+),
--   3. adds background compression policies for new chunks,
--   4. adds 14-day retention on the RAW ticks only (bars are kept forever,
--      compressed).
--
-- Safe with the continuous aggregates (cagg_bars_1m/10m/30m): already-
-- materialized bars keep their data; only re-aggregating dropped raw ticks is
-- lost, which the platform never does.
--
-- Idempotent: policies use if_not_exists; compress_chunk uses if_not_compressed.
-- Run via psql (autocommit per statement), NOT inside one big transaction.
-- ============================================================

-- 1) Compression configuration (segment by instrument, newest-first).
ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id',
    timescaledb.compress_orderby = 'ts DESC'
);
ALTER TABLE quotes_l1 SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id',
    timescaledb.compress_orderby = 'ts DESC'
);
ALTER TABLE bars SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id, resolution',
    timescaledb.compress_orderby = 'ts DESC'
);

-- 2) One-time immediate reclaim: compress every chunk older than 2 days now
--    (don't wait for the background policy's first run).
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('trades', older_than => INTERVAL '2 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('quotes_l1', older_than => INTERVAL '2 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('bars', older_than => INTERVAL '7 days') AS c;

-- 3) Background compression policies for chunks as they age.
SELECT add_compression_policy('trades',    INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('quotes_l1', INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('bars',      INTERVAL '7 days', if_not_exists => TRUE);

-- 4) Retention on the raw ticks only. Adjust the interval to how much raw tick
--    history you want to keep (bars are unaffected — kept forever, compressed).
SELECT add_retention_policy('trades',    INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_retention_policy('quotes_l1', INTERVAL '14 days', if_not_exists => TRUE);
