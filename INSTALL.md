# Step 15 — 1-Minute OHLCV Continuous Aggregate

Single file in this archive:

- `migrations/versions/0003_bars_1m_continuous_aggregate.sql` — creates `cagg_bars_1m` continuous aggregate, backfills, schedules refresh policy

## Apply

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step15-bars-1m.zip
git add -A
git commit -m "Step 15: 1m OHLCV continuous aggregate from trades"
git push
```

## Run the Migration (on the Lightsail box)

```bash
git pull
docker exec -i signal_postgres psql -U signal -d signal_platform \
  < ~/app/migrations/versions/0003_bars_1m_continuous_aggregate.sql
```

Expected output: `CREATE MATERIALIZED VIEW`, `CALL` (the backfill), the policy ID
as a return value, `CREATE INDEX`, `CREATE VIEW`. Total runtime: a few seconds.

## Verify

```bash
docker exec -it signal_postgres psql -U signal -d signal_platform -c "
SELECT canonical_symbol,
       count(*) AS bars,
       min(bucket) AS first_bar,
       max(bucket) AS last_bar
FROM bars_1m_view
GROUP BY canonical_symbol
ORDER BY canonical_symbol;
"
```

Expected: 2-4 rows (depending on how many of your instruments have trades),
with `bars` count in the thousands, `first_bar` around 2026-05-21, `last_bar`
within the last few minutes.

No app code changes this step — the API and frontend continue as before.
The aggregate is now ready for Step 17 to expose via a `/market/bars` endpoint.
