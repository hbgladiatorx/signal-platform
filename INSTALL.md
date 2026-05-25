# Step 31 v2 — Corrected Historical Backfill

The prior backfill wrote to the wrong place. This one synthesizes trades that round-trip through the cagg's aggregation semantics correctly.

## What This Replaces

`packages/backtest/historical_backfill.py` — completely rewritten.

## Apply

```bash
# Mac
cd ~/signal-platform
unzip -o ~/Downloads/step31-backfill-v2.zip
git add -A
git commit -m "Step 31 v2: synthetic-trades backfill (replaces broken v1)"
git push

# Box
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
sleep 10
```

## Step 0 — Clean Up The Dead 1d Bars From v1

The 1827 rows we inserted into `bars` table are dead. Delete them:

```bash
docker exec signal_postgres psql -U signal -d signal_platform -c "
  DELETE FROM bars
  WHERE resolution = '1d'
    AND ts < '2026-05-01';
"
```

Should show `DELETE 1827`. The `< 2026-05-01` clause makes this surgical — only deletes pre-real-time rows, leaves any live-ingested data alone (there shouldn't be any 1d rows from real-time, but defensive).

## Step 1 — Tiny Smoke Test (1 day, 1 symbol)

Single day of BTC-USDT, ~1440 klines → 5760 synthetic trades. Should take ~5 seconds plus the cagg refresh chain.

```bash
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS \
  --start 2025-05-01 \
  --end 2025-05-02
```

Expect output like:
```
Backfill plan:
  Symbol: BTC-USDT@BINANCEUS
  Range: 2025-05-01... → 2025-05-02...
  Estimated klines: 1,440
  ...
Fetch + insert: 1.2s
  Klines fetched: 1,440
  Trades synthesized: 5,760
  Trades inserted: 5,760

Refreshing continuous aggregates...
  [cagg_bars_1m] refreshing 2025-05-01 → 2025-05-02 ... done in 0.4s
  [cagg_bars_5m] refreshing ...
  [cagg_bars_15m] refreshing ...
  [cagg_bars_1h] refreshing ...
  [cagg_bars_4h] refreshing ...
  [cagg_bars_1d] refreshing ...

VERIFY cagg_bars_1d in range: 1 buckets, 2025-05-01 → 2025-05-01

DONE. Total wall time: ~5s
```

## Step 2 — Verify The Synthesis Math

Compare a single day's OHLCV in the cagg with the source kline from Binance.US directly:

```bash
docker exec signal_postgres psql -U signal -d signal_platform -c "
  SELECT bucket, open, high, low, close, volume, trade_count
  FROM cagg_bars_1d
  WHERE instrument_id = 1 AND bucket = '2025-05-01'
"

# Compare to Binance.US source for that day:
curl -s 'https://api.binance.us/api/v3/klines?symbol=BTCUSDT&interval=1d&startTime=1746057600000&endTime=1746144000000' | python3 -m json.tool
```

Open, high, low, close should **match exactly** between cagg and Binance.
Volume should match exactly.
Trade count from cagg will be `4 × number_of_minutes_with_volume` instead of the real trade count — expected difference.

## Step 3 — Run A Real Backtest

Now your SMACrossover backtest on BTC-USDT at 1d resolution will see real data for 2025-05-01. The Period column should show **1.0d** but **with verified real data underneath**.

If the smoke test verifies cleanly, scale up:

```bash
# 1 month
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS \
  --start 2025-04-01 --end 2025-05-01

# 1 year (~80s fetch, plus cagg refresh)
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS \
  --start 2025-01-01 --end 2026-01-01

# Multiple symbols
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol ETH-USDT@BINANCEUS \
  --start 2025-01-01 --end 2026-01-01
```

## Safety Built In

- **Overlap guard**: refuses to insert if range overlaps existing real trades. Caps `--end` to safely precede earliest real data.
- **Idempotent**: `venue_trade_id` is deterministic. Re-running same range is a no-op.
- **Scoped cagg refresh**: refresh only covers the backfilled window; existing materializations outside the window are not touched.
- **Zero-volume bars skipped**: pre-listing windows don't generate fake trades.

## Known Limitations

- **trade_count is 4× per minute** (always), not the real Binance count
- **VWAP is approximate**: (O+H+L+C)/4 typical price approximation rather than true VWAP from individual trades. Within a few bps of real for normal markets.
- **Side is NULL**: synthetic trades don't have buyer/seller-initiated information
- **One symbol per invocation**

## If Something Goes Wrong

Roll back the backfill for a specific range:

```bash
docker exec signal_postgres psql -U signal -d signal_platform -c "
  DELETE FROM trades
  WHERE venue_trade_id LIKE 'backfill-%'
    AND ts >= '2025-05-01'
    AND ts < '2025-05-02';
"
# Then refresh caggs for the same range to deduplicate
docker exec signal_postgres psql -U signal -d signal_platform -c "
  CALL refresh_continuous_aggregate('cagg_bars_1m', '2025-05-01', '2025-05-02');
  CALL refresh_continuous_aggregate('cagg_bars_5m', '2025-05-01', '2025-05-02');
  CALL refresh_continuous_aggregate('cagg_bars_15m', '2025-05-01', '2025-05-02');
  CALL refresh_continuous_aggregate('cagg_bars_1h', '2025-05-01', '2025-05-02');
  CALL refresh_continuous_aggregate('cagg_bars_4h', '2025-05-01', '2025-05-02');
  CALL refresh_continuous_aggregate('cagg_bars_1d', '2025-05-01', '2025-05-02');
"
```

The `venue_trade_id LIKE 'backfill-%'` filter means this only removes synthesized trades — real trades from live ingestion are untouched.
