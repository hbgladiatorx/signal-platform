# Step 18 — Live Bar-Builder Service

Files in this archive:

- `services/bar_builder/__init__.py` — NEW: package marker
- `services/bar_builder/main.py` — NEW: the bar-builder service itself
- `packages/data/messagebus.py` — REPLACED: adds STREAM_BARS_LIVE, STREAM_BARS_CLOSED, GROUP_BAR_BUILDER constants (everything else preserved)
- `docker-compose.yml` — REPLACED: adds the `bar_builder` service (all 7 existing services preserved)

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step18-bar-builder.zip
git status
```

Expected from `git status`:
- 2 modified: `packages/data/messagebus.py`, `docker-compose.yml`
- 1 new directory tree: `services/bar_builder/` (containing `__init__.py`, `main.py`)
- 1 modified: `INSTALL.md`

Commit and push:

```bash
git add -A
git commit -m "Step 18: live bar-builder service"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build bar_builder
docker compose up -d bar_builder
```

The `bar_builder` service is independent — it doesn't share images with api/frontend/etc. (well, it shares the python image build, but only the bar_builder container needs (re)creating). No need to recreate other services.

## Verify

Check the new container is running:

```bash
docker compose ps bar_builder
docker compose logs --tail=30 bar_builder
```

Expected logs:
- `bar_builder.starting` with stream/group/consumer/resolutions fields
- Periodic `bar_builder.bar_closed` events as 1m buckets transition (~every minute when trades occur)

Confirm the consumer group registered with Redis:

```bash
docker exec signal_redis redis-cli XINFO GROUPS trades:raw
```

Expected: 3 groups now (was 2): `persistence`, `ws-broadcast`, `bar-builder`.

Confirm the new streams are receiving data:

```bash
docker exec signal_redis redis-cli XLEN bars:live
docker exec signal_redis redis-cli XLEN bars:closed
```

Expected: `bars:live` ramps up to ~12 entries per second (2 instruments × 6 resolutions). `bars:closed` ticks slowly (~1m bars close every minute).

Peek at the latest entry:

```bash
docker exec signal_redis redis-cli XREVRANGE bars:live + - COUNT 1
```

Expected: a single entry whose `payload` field contains JSON with `instrument_id`, `canonical_symbol`, `resolution`, `bucket_start`, OHLCV, `vwap`, `closed: false`.
