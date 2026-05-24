# Step 31 MVP — Historical Backfill Script

One Python file. Pulls historical bars from Binance.US REST `/api/v3/klines` and INSERTs into the existing `bars` hypertable. Idempotent.

## What This Ships

- `packages/backtest/historical_backfill.py` — standalone async script

**Nothing else changes.** No new container, no migration, no API endpoint, no UI. The script reaches the running API container via `docker exec`.

## Apply / Deploy

```bash
# Mac
cd ~/signal-platform
unzip -o ~/Downloads/step31-backfill.zip
git add -A
git commit -m "Step 31 MVP: historical backfill script from Binance.US klines"
git push

# Box
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
sleep 10

# Smoke test (should print the script's --help)
docker exec signal_api python -m packages.backtest.historical_backfill --help
```

If the help text prints, the script is in place.

## Run Your First Backfill

Start small — 1 month of 1d bars (fast, low risk):

```bash
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS \
  --resolution 1d \
  --start 2025-01-01 \
  --end 2026-01-01
```

You should see:
```
Backfill plan:
  Symbol:          BTC-USDT@BINANCEUS
  Resolution:      1d
  Range:           2025-01-01... → 2026-01-01...
  Estimated bars:  365
  Estimated calls: 1
  Estimated time:  ~0s

Resolved: instrument_id=1 native_symbol=BTCUSDT
Existing rows for this instrument/resolution: 0

  [100.0%] fetched=365 inserted=365 ...

============================================================
DONE
  Wall time:           1.2s
  Bars fetched:        365
  New rows inserted:   365
  Skipped duplicates:  0
  Existing before:     0
  Existing after:      365
  Net new:             365
```

## Verify in the DB

```bash
docker exec signal_postgres psql -U signal -d signal_platform -c "
  SELECT count(*), min(ts), max(ts)
  FROM bars
  WHERE instrument_id = 1 AND resolution = '1d'
"
```

Should show 365 rows spanning 2025.

## Now Run a Real Backtest

In the UI:
1. Go to `/strategies`
2. Pick SMACrossover
3. New backtest:
   - Symbol: BTC-USDT@BINANCEUS
   - Resolution: 1d
   - (set start/end if the form asks; otherwise it'll use what's available)
4. Run

When you open the result, the **Period tested** field should show `1.0 years` or so — **GREEN**. The first time you'll have a backtest worth looking at.

## Scale Up When Comfortable

Once you trust the script:

```bash
# 1 year of 1m bars (~80 seconds)
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS --resolution 1m \
  --start 2025-01-01 --end 2026-01-01

# 5 years of 1h bars (~10 seconds)
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol BTC-USDT@BINANCEUS --resolution 1h \
  --start 2021-01-01 --end 2026-01-01

# Same for ETH
docker exec -it signal_api python -m packages.backtest.historical_backfill \
  --symbol ETH-USDT@BINANCEUS --resolution 1m \
  --start 2025-01-01 --end 2026-01-01
```

Re-running the same command is a no-op (`Skipped duplicates: N`). Safe.

## Rate-Limit Behavior

Self-limited to 400 calls/min. Binance.US allows 600. Headroom is for real-time ingestion which shares the rate limit budget.

If you get repeated 429s in the script output, lower `SELF_RATE_LIMIT_CALLS_PER_MIN` at the top of the file. You shouldn't see any in normal use.

## Known Limitations

| Limitation | Workaround |
|------------|-----------|
| One symbol per invocation | Run the script multiple times |
| No cancellation / pause / resume | Just kill it; idempotent, restart from scratch |
| Continuous aggregates (5m/15m/1h etc.) NOT refreshed | If you backfill 1m and your platform has caggs, manually `CALL refresh_continuous_aggregate('cagg_name', ...)` afterwards. OR just backfill the resolution you'll use directly (cheaper at lower resolutions). |
| Pre-listing windows return empty | Script handles gracefully — prints `[empty]` and advances |
| Hard-coded Binance.US (not generalizable) | Future step: extract to a per-venue backfill abstraction |

## Cleanup Carryover (Added)

- **Step 31 follow-ups**: Wrap the script in a worker container + API endpoints + UI flow (the full Step 31 spec). Once you have a few hundred MB of historical bars, the platform's UX should expose backfill triggering visually instead of via `docker exec`.
- **Cagg refresh trigger** if you decide to use the continuous aggregates rather than backfilling each resolution directly.
