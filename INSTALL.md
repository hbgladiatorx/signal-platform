# Step 21 — Performance Analytics

Files in this archive:

- `packages/backtest/analytics.py` — NEW: `compute_analytics()`, `BacktestAnalytics`, `RoundTrip`
- `packages/backtest/__init__.py` — UPDATED: re-exports the new analytics types

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step21-analytics.zip
git add -A
git commit -m "Step 21: performance analytics (Sharpe, Sortino, drawdown, round trips)"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
```

## Verify

Run a backtest + analytics on real BTC data:

```bash
docker exec -i signal_api python3 << 'EOF'
import asyncio
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from packages.backtest import BacktestConfig, compute_analytics, run_backtest
from packages.data.db import get_engine
from packages.strategy.registry import discover_strategies


async def load_bars(symbol, table):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(f"""
                SELECT b.bucket, b.open, b.high, b.low, b.close, b.volume
                FROM {table} b
                JOIN instruments i ON i.id = b.instrument_id
                WHERE i.canonical_symbol = :symbol
                ORDER BY b.bucket
            """),
            {"symbol": symbol},
        )
        rows = result.mappings().all()
    df = pd.DataFrame(rows)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    df = df.set_index("bucket")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


async def main():
    symbol = "BTC-USDT@BINANCEUS"
    bars = await load_bars(symbol, "cagg_bars_1h")
    print(f"Loaded {len(bars)} bars")

    SMACrossover = discover_strategies(Path("/app/strategies"))["SMACrossover"]
    params = SMACrossover.PARAMS_MODEL(fast_period=5, slow_period=20, position_size=0.001)
    strategy = SMACrossover(symbols=[symbol], params=params)
    config = BacktestConfig(starting_cash=Decimal("10000"))

    result = run_backtest(strategy, {symbol: bars}, config)
    a = compute_analytics(result)

    print(f"\n=== Returns ===")
    print(f"  Total:        {a.total_return_pct:.4f}%")
    print(f"  Annualized:   {a.annualized_return_pct:.4f}%" if a.annualized_return_pct else "  Annualized:   None")

    print(f"\n=== Risk ===")
    print(f"  Sharpe:       {a.sharpe_ratio:.4f}" if a.sharpe_ratio else "  Sharpe:       None")
    print(f"  Sortino:      {a.sortino_ratio:.4f}" if a.sortino_ratio else "  Sortino:      None")
    print(f"  Max DD:       {a.max_drawdown_pct:.4f}%")
    if a.max_drawdown_peak_ts:
        print(f"    Peak:       {a.max_drawdown_peak_ts:%Y-%m-%d %H:%M}")
        print(f"    Trough:     {a.max_drawdown_trough_ts:%Y-%m-%d %H:%M}")
    print(f"  Calmar:       {a.calmar_ratio:.4f}" if a.calmar_ratio else "  Calmar:       None")
    print(f"  Periods/yr:   {a.periods_per_year:.0f}")

    print(f"\n=== Trades ===")
    print(f"  Closed:       {a.num_closed_trades}")
    print(f"  Open:         {a.num_open_trades}")
    print(f"  Win rate:     {a.win_rate_pct}%" if a.win_rate_pct is not None else "  Win rate:     None")
    print(f"  Profit factor:{f' {a.profit_factor:.4f}' if a.profit_factor else ' None'}")
    print(f"  Avg winner:   {a.avg_winner_pct:.4f}%" if a.avg_winner_pct else "  Avg winner:   None")
    print(f"  Avg loser:    {a.avg_loser_pct:.4f}%" if a.avg_loser_pct else "  Avg loser:    None")

    if a.closed_round_trips:
        print(f"\n=== Round Trips ===")
        for i, rt in enumerate(a.closed_round_trips, 1):
            print(f"  #{i}: {rt.entry_ts:%m-%d %H:%M} -> {rt.exit_ts:%m-%d %H:%M}  "
                  f"${rt.entry_avg_price:.2f} -> ${rt.exit_avg_price:.2f}  "
                  f"net_pnl=${rt.net_pnl:.4f} ({rt.duration_seconds/3600:.1f}h)")


asyncio.run(main())
EOF
```

Expected: a full analytics breakdown including any closed round trips
and any open positions. With ~57 1h bars over 2.5 days, the strategy
won't have generated many trades — but the analytics will compute
cleanly for whatever it produced.
