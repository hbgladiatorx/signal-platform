# Step 12.1 — System Health page patches

Three fixes:

1. **Trade vs quote thresholds**: trades are sparse on small venues,
   so separate looser thresholds for trade age (5min/30min) vs quote
   age (30s/2min).
2. **Endpoint latency**: queries run in parallel via asyncio.gather;
   ingestion LATERAL scans bounded to 24h/15min instead of 1 day.
3. **Hypertable row counts**: sum reltuples across chunks via
   pg_inherits so we don't get the -1 from the parent table.

Two files updated:
- `services/api/routers/system.py` — REPLACED
- `frontend/app/system/health/page.tsx` — REPLACED

## Apply

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step12-patch.zip
git add -A
git commit -m "Step 12 patches: separate trade/quote thresholds, parallel queries, real row counts"
git push
```

Then on the box:

```bash
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
```
