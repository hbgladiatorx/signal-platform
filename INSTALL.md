# Step 20 — Backtest Engine

Files in this archive:

- `packages/backtest/__init__.py` — public API re-exports
- `packages/backtest/types.py` — `BacktestConfig`, `BacktestResult`, `Fill`, `Position`, `EquityPoint`
- `packages/backtest/portfolio.py` — `Portfolio` (cash + positions with avg-cost accounting)
- `packages/backtest/fills.py` — market and limit order fill simulation
- `packages/backtest/engine.py` — `run_backtest()` main function

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step20-backtest-engine.zip
git add -A
git commit -m "Step 20: backtest engine (run_backtest, Portfolio, fills, types)"
git push
```

## Deploy (Box)

Pull and rebuild the API. We don't have a backtest worker yet (that's Step 22), so we'll verify by running a backtest directly inside the API container.

```bash
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
```

## Verify with Real Data

Run a backtest against BTC-USDT 1h bars from your TimescaleDB. Inside the API container:

```bash
docker exec -it signal_api python3 << 'EOF'
import asyncio
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from packages.backtest import BacktestConfig, run_backtest
from packages.data.db import get_engine
from packages.strategy.registry import discover_strategies


async def load_bars(symbol: str, resolution_table: str) -> pd.DataFrame:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(f"""
                SELECT b.bucket, b.open, b.high, b.low, b.close, b.volume
                FROM {resolution_table} b
                JOIN instruments i ON i.id = b.instrument_id
                WHERE i.canonical_symbol = :symbol
                ORDER BY b.bucket
            """),
            {"symbol": symbol},
        )
        rows = result.mappings().all()
    if not rows:
        raise RuntimeError(f"No bars found for {symbol} in {resolution_table}")
    df = pd.DataFrame(rows)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    df = df.set_index("bucket")
    # Convert Decimal columns to float for pandas math
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


async def main():
    symbol = "BTC-USDT@BINANCEUS"
    print(f"Loading 1h bars for {symbol}...")
    bars = await load_bars(symbol, "cagg_bars_1h")
    print(f"  Got {len(bars)} bars, {bars.index[0]} to {bars.index[-1]}")

    strategies = discover_strategies(Path("/app/strategies"))
    SMACrossover = strategies["SMACrossover"]

    params = SMACrossover.PARAMS_MODEL(
        fast_period=5,
        slow_period=20,
        position_size=0.001,  # 0.001 BTC per entry — small position
    )
    strategy = SMACrossover(symbols=[symbol], params=params)

    config = BacktestConfig(
        starting_cash=Decimal("10000"),
        fee_rate_bps=10,
        slippage_bps=5,
    )

    print(f"\nRunning backtest: fast=5, slow=20...")
    result = run_backtest(strategy, {symbol: bars}, config)

    print(f"\n=== Result ===")
    print(f"Starting cash:  ${result.config.starting_cash}")
    print(f"Final equity:   ${result.final_equity:.4f}")
    print(f"Total return:   {result.total_return_pct:.4f}%")
    print(f"Trades:         {result.num_trades}")
    print(f"Rejected:       {result.num_rejected}")
    print(f"Equity points:  {len(result.equity_curve)}")

    if result.fills:
        print(f"\n=== Fills ===")
        for f in result.fills:
            print(f"  {f.filled_ts:%Y-%m-%d %H:%M} {f.side.value:4} {f.quantity} @ ${f.price:.2f} fee=${f.fee:.4f}")


asyncio.run(main())
EOF
```

Expected: a backtest run on your ~110 BTC 1h bars, showing some number of
fills (could be 0 if no crossover signals fired in the data window — 2.5
days is small) and a total return percentage. Even if it lost money or
broke even, the run completing cleanly is success.
