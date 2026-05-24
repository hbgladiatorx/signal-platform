# Step 22b — Backtest Worker Service

Files in this archive:

- `services/backtest_worker/__init__.py` — NEW: package marker
- `services/backtest_worker/main.py` — NEW: the worker
- `packages/data/messagebus.py` — UPDATED: adds `QUEUE_BACKTEST_JOBS` constant
- `docker-compose.yml` — UPDATED: adds `backtest_worker` service

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step22b-worker.zip
git add -A
git commit -m "Step 22b: backtest_worker service (Redis LIST queue)"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build backtest_worker
docker compose up -d backtest_worker
```

Then verify the service is running and idle (queue is empty, so it should be blocking on BRPOP):

```bash
docker compose ps backtest_worker
docker compose logs --tail=10 backtest_worker
```

Expected log line: `backtest_worker.starting` showing `queue=backtest:jobs` and `strategies=['SMACrossover']`.

## End-to-End Verification

We need to: create a pending backtest, push its UUID onto the Redis queue, watch the worker pick it up and complete it.

### Step 1: Create a pending backtest

```bash
docker exec -i signal_api python3 << 'EOF'
import asyncio
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from packages.backtest.persistence import create_backtest
from packages.data.db import get_engine
from packages.strategy.registry import discover_strategies


async def main():
    engine = get_engine()
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT id, org_id FROM users LIMIT 1")
        )).mappings().first()
        user_id, org_id = row["id"], row["org_id"]

    SMACrossover = discover_strategies(Path("/app/strategies"))["SMACrossover"]
    params = SMACrossover.PARAMS_MODEL(fast_period=5, slow_period=20, position_size=0.001)

    async with engine.begin() as conn:
        bt_id = await create_backtest(
            conn,
            user_id=user_id, org_id=org_id,
            strategy_name=SMACrossover.name(),
            params_json=params.model_dump(),
            symbols=["BTC-USDT@BINANCEUS"],
            bar_resolution="1h",
            starting_cash=Decimal("10000"),
        )
    print(f"BACKTEST_ID={bt_id}")


asyncio.run(main())
EOF
```

Note the printed `BACKTEST_ID=...` UUID. We'll push that.

### Step 2: Enqueue the job

Copy the UUID from above into:

```bash
BT_ID=<paste-uuid-here>
docker exec signal_redis redis-cli LPUSH backtest:jobs "$BT_ID"
```

Expected output: `(integer) 1` — one item now in the queue.

### Step 3: Watch the worker process it

```bash
sleep 3
docker compose logs --tail=20 backtest_worker
```

Expected: log lines `backtest_worker.job.start` → `backtest_worker.job.bars_loaded` → `backtest_worker.job.computed` → `backtest_worker.job.completed`.

### Step 4: Confirm the backtest is in the DB as 'completed'

```bash
docker exec -i signal_postgres psql -U signal -d signal_platform -c "
  SELECT id, status, total_return_pct, num_closed_trades, num_open_trades,
         duration_seconds, completed_at
  FROM backtests
  ORDER BY created_at DESC
  LIMIT 3;
"
```

Expected: the new row has `status='completed'`, populated metrics, populated `completed_at`.

### Step 5 (optional): inspect trades and equity

```bash
docker exec -i signal_postgres psql -U signal -d signal_platform -c "
  SELECT COUNT(*) AS trades_in_db FROM backtest_trades WHERE backtest_id = '$BT_ID';
"

docker exec -i signal_postgres psql -U signal -d signal_platform -c "
  SELECT COUNT(*) AS equity_in_db FROM backtest_equity_points WHERE backtest_id = '$BT_ID';
"
```

Expected: 1 trade, 57 equity points (matching prior in-process test results).
