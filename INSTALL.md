# Step 16 — Higher-Resolution Bar Aggregates (5m / 15m / 1h / 4h / 1d)

Single migration in this archive:

- `migrations/versions/0004_higher_resolution_bars.sql`

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step16-higher-res-bars.zip
git add -A
git commit -m "Step 16: 5m/15m/1h/4h/1d continuous aggregates"
git push
```

## Run Migration (Box)

```bash
cd ~/app
git pull
docker exec -i signal_postgres psql -U signal -d signal_platform \
  < migrations/versions/0004_higher_resolution_bars.sql
```

Expected output: 5 × (CREATE MATERIALIZED VIEW, CALL, policy ID returned, CREATE INDEX), plus 5 × CREATE VIEW.

## Verify (Box)

```bash
docker exec -it signal_postgres psql -U signal -d signal_platform -c "
SELECT '1m' AS res, count(*) FROM cagg_bars_1m
UNION ALL SELECT '5m', count(*) FROM cagg_bars_5m
UNION ALL SELECT '15m', count(*) FROM cagg_bars_15m
UNION ALL SELECT '1h', count(*) FROM cagg_bars_1h
UNION ALL SELECT '4h', count(*) FROM cagg_bars_4h
UNION ALL SELECT '1d', count(*) FROM cagg_bars_1d;
"
```

Expected: row counts decreasing as resolution grows coarser.

Confirm all auto-refresh policies registered:

```bash
docker exec -it signal_postgres psql -U signal -d signal_platform -c "
SELECT j.job_id, j.hypertable_name, j.schedule_interval
FROM timescaledb_information.jobs j
WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
ORDER BY j.job_id;
"
```

Expected: 6 rows (policy for 1m from Step 15 + 5 new policies).
