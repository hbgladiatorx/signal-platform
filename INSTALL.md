# Step 22a — Backtest Persistence (Schema + Helpers)

Files in this archive:

- `migrations/versions/0005_backtest_tables.sql` — NEW: 3 tables (backtests, backtest_trades, backtest_equity_points)
- `packages/backtest/persistence.py` — NEW: DB helper functions

No service changes in 22a — the worker comes in 22b.

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step22a-persistence.zip
git status
git add -A
git commit -m "Step 22a: backtest persistence schema + helpers"
git push
```

## Deploy (Box)

### 1. Pull and rebuild the API container

```bash
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
```

### 2. Apply the migration manually

We don't have automatic migration application set up. Run the SQL manually
against the running Postgres container:

```bash
docker exec -i signal_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < migrations/versions/0005_backtest_tables.sql
```

(The `$POSTGRES_USER` and `$POSTGRES_DB` env vars are set in your `.env`;
the bash session on the box should have them. If not, substitute literal
values from `.env`.)

Expected output: a sequence of `CREATE EXTENSION` / `CREATE TABLE` /
`CREATE INDEX` lines, all returning successfully.

### 3. Verify the schema

```bash
docker exec -i signal_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt backtest*"
docker exec -i signal_postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d+ backtests"
```

Expected: three tables listed (`backtests`, `backtest_trades`, `backtest_equity_points`), plus the full column layout of `backtests` showing summary metrics, lifecycle columns, FKs to users/organizations.

### 4. End-to-end verification

Run a backtest in-process and persist it to the new tables, then query back:

```bash
docker exec -i signal_api python3 << 'EOF'
import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import text

from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.backtest.persistence import (
    create_backtest,
    mark_backtest_running,
    save_backtest_results,
    load_backtest,
    load_backtest_trades,
    load_backtest_equity,
)
from packages.data.db import get_engine
from packages.strategy.registry import discover_strategies


async def main():
    engine = get_engine()

    # 1) Look up an existing user + org to attribute the backtest to.
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT id, organization_id FROM users LIMIT 1")
        )).mappings().first()
        if not row:
            print("No users found; cannot proceed.")
            return
        user_id = row["id"]
        org_id = row["organization_id"]
    print(f"Using user_id={user_id}, organization_id={org_id}")

    # 2) Load real BTC bars.
    symbol = "BTC-USDT@BINANCEUS"
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT b.bucket, b.open, b.high, b.low, b.close, b.volume
            FROM cagg_bars_1h b
            JOIN instruments i ON i.id = b.instrument_id
            WHERE i.canonical_symbol = :s
            ORDER BY b.bucket
        """), {"s": symbol})).mappings().all()
    bars = pd.DataFrame(rows)
    bars["bucket"] = pd.to_datetime(bars["bucket"], utc=True)
    bars = bars.set_index("bucket")
    for col in ("open", "high", "low", "close", "volume"):
        bars[col] = bars[col].astype(float)
    print(f"Loaded {len(bars)} bars: {bars.index[0]} -> {bars.index[-1]}")

    # 3) Set up the strategy.
    SMACrossover = discover_strategies(Path("/app/strategies"))["SMACrossover"]
    params = SMACrossover.PARAMS_MODEL(fast_period=5, slow_period=20, position_size=0.001)
    strategy = SMACrossover(symbols=[symbol], params=params)
    config = BacktestConfig(starting_cash=Decimal("10000"))

    # 4) Create the backtest row.
    async with engine.begin() as conn:
        backtest_id = await create_backtest(
            conn,
            user_id=user_id,
            organization_id=org_id,
            strategy_name=SMACrossover.name(),
            params_json=params.model_dump(),
            symbols=[symbol],
            bar_resolution="1h",
            starting_cash=config.starting_cash,
            fee_rate_bps=config.fee_rate_bps,
            slippage_bps=config.slippage_bps,
        )
    print(f"Created backtest {backtest_id}")

    # 5) Transition to running, execute, persist.
    async with engine.begin() as conn:
        await mark_backtest_running(conn, backtest_id)

    result = run_backtest(strategy, {symbol: bars}, config)
    analytics = compute_analytics(result)
    print(f"Ran backtest: {result.num_trades} fills, {analytics.num_closed_trades} closed trips")

    async with engine.begin() as conn:
        await save_backtest_results(
            conn, backtest_id, result, analytics,
            bars_start=bars.index[0].to_pydatetime(),
            bars_end=bars.index[-1].to_pydatetime(),
            num_bars=len(bars),
        )
    print(f"Persisted results")

    # 6) Read back to confirm round-trip.
    async with engine.connect() as conn:
        header = await load_backtest(conn, backtest_id)
        trades = await load_backtest_trades(conn, backtest_id)
        equity = await load_backtest_equity(conn, backtest_id)

    print(f"\n=== Persisted Backtest ===")
    print(f"  id:              {header['id']}")
    print(f"  status:          {header['status']}")
    print(f"  strategy_name:   {header['strategy_name']}")
    print(f"  total_return:    {header['total_return_pct']}%")
    print(f"  sharpe_ratio:    {header['sharpe_ratio']}")
    print(f"  max_drawdown:    {header['max_drawdown_pct']}%")
    print(f"  num_closed:      {header['num_closed_trades']}")
    print(f"  num_open:        {header['num_open_trades']}")
    print(f"  win_rate:        {header['win_rate_pct']}%")
    print(f"  duration_s:      {header['duration_seconds']}")
    print(f"  bars_start..end: {header['bars_start']} -> {header['bars_end']}")
    print(f"\nTrades persisted: {len(trades)}")
    print(f"Equity points persisted: {len(equity)}")

    if trades:
        rt = trades[0]
        print(f"\nFirst trade: ${rt['entry_avg_price']} -> ${rt['exit_avg_price']} "
              f"net_pnl=${rt['net_pnl']}")


asyncio.run(main())
EOF
```

Expected: a backtest gets created, runs, and the persistence layer round-trips
the full result. The header should show summary metrics matching what
analytics computed. Trades and equity points are persisted in their own
tables.

## What's Next: Step 22b

After confirming 22a, we ship the `backtest_worker` service that consumes
a Redis queue and triggers `run_backtest` + persistence automatically.
That decouples job creation (Step 23's API) from job execution.
