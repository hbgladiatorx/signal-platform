-- 0026_market_data_retention.sql
-- ============================================================
-- Reclaim disk: compress the market-data hypertables + continuous aggregates,
-- and drop stale raw ticks.
--
-- Volume was ~38 GB, almost all in the DB:
--   * continuous aggregates (cagg_bars_1m 8.6 GB, 5m 4.6 GB, 15m 2.2 GB, ...) ~19 GB
--   * trades (raw ticks, 5.6 yrs)                                             ~13 GB
--   * quotes_l1                                                               ~2.3 GB
--
-- Backtests read the cagg_bars_* views (already materialized), NOT raw trades.
-- So we COMPRESS the caggs (keep all history, still queryable) and the raw
-- hypertables, and DROP raw ticks older than 14 days (only used to build bars).
--
-- Run via psql (autocommit per statement) — several functions here (drop_chunks)
-- must not run inside a single transaction block. The one-time compression of
-- ~19 GB of caggs can take a few minutes.
--
-- Idempotent: policies use if_not_exists; compress uses if_not_compressed.
-- ============================================================

-- ---- Raw hypertables: compression config ----
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

-- ---- Immediate reclaim: drop raw ticks older than 14 days (the 5.6-yr history).
--      Backtests read caggs, so this is safe. Drop BEFORE compressing so we don't
--      waste effort compressing chunks we're about to remove.
SELECT drop_chunks('trades',    older_than => INTERVAL '14 days');
SELECT drop_chunks('quotes_l1', older_than => INTERVAL '14 days');

-- ---- Compress the recent raw chunks that remain.
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('trades', older_than => INTERVAL '2 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('quotes_l1', older_than => INTERVAL '2 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE)
FROM show_chunks('bars', older_than => INTERVAL '7 days') AS c;

-- ---- Background policies for new chunks.
SELECT add_compression_policy('trades',    INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('quotes_l1', INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('bars',      INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('trades',    INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_retention_policy('quotes_l1', INTERVAL '14 days', if_not_exists => TRUE);

-- ============================================================
-- Continuous aggregates: COMPRESS (no retention — these ARE the backtest data,
-- so we keep every bar, just stored ~80-90% smaller and still queryable).
-- ============================================================
ALTER MATERIALIZED VIEW cagg_bars_1m  SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_5m  SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_10m SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_15m SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_30m SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_1h  SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_4h  SET (timescaledb.compress = true);
ALTER MATERIALIZED VIEW cagg_bars_1d  SET (timescaledb.compress = true);

-- One-time compression of existing cagg chunks older than 7 days.
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_1m',  older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_5m',  older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_10m', older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_15m', older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_30m', older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_1h',  older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_4h',  older_than => INTERVAL '7 days') AS c;
SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('cagg_bars_1d',  older_than => INTERVAL '7 days') AS c;

-- Background compression policies for the caggs.
SELECT add_compression_policy('cagg_bars_1m',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_5m',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_10m', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_15m', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_30m', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_1h',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_4h',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('cagg_bars_1d',  INTERVAL '7 days', if_not_exists => TRUE);

-- After this completes, reclaim OS space held by dropped/rewritten chunks:
--   VACUUM;    -- (run separately; VACUUM cannot run inside a transaction block)
