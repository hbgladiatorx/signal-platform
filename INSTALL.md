# Step 32 — Strategy Parameter Sweep UI

A new page at **`/backtests/sweep`** that runs one strategy across a grid of parameter values, displays results inline sorted by Sharpe.

## What This Ships

- **`frontend/app/backtests/sweep/page.tsx`** (NEW, ~400 lines)

That's it. Pure frontend. Reuses the existing `POST /backtests` API (which already accepts a `params: dict[str, Any]` field per its schema). No backend changes, no migrations.

## Apply

```bash
# Mac
cd ~/signal-platform
unzip -o ~/Downloads/step32-sweep.zip
git add -A
git commit -m "Step 32: strategy parameter sweep UI"
git push

# Box (after the BTC backfill finishes — frontend can rebuild while DB is busy)
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
```

## How To Use

Navigate to **`https://signal.cimcha.com/backtests/sweep`** directly (no nav link yet — that's a polish item).

The form has two sections:

**1. Sweep configuration:** strategy, symbol, resolution, starting cash, fee bps, slippage bps. Standard backtest fields.

**2. Parameter grid:** a textarea with one parameter per line:

```
fast_window: 5, 10, 20
slow_window: 50, 100, 200
```

Live preview at the bottom shows the combo count (here, 9 = 3 × 3).

Submit → page switches to "results mode" with a sortable table:

| fast_window | slow_window | Status | Return | Sharpe | Max DD | Trades | Win % |
|-------------|-------------|--------|--------|--------|--------|--------|-------|
| 10 | 50 | completed | +2.1% | 0.42 | -1.8% | 14 | 64% |
| 5 | 200 | completed | -0.8% | -0.31 | -3.2% | 8 | 25% |
| ... | ... | ... | ... | ... | ... | ... | ... |

Sorted by Sharpe descending — best strategy on top.

Each row has a `detail →` link to the full backtest result page.

## Critical First Test — Verify Params Are Actually Used

Before running a big sweep, do a 2-combo sanity check to confirm the backend uses the params field rather than the strategy's hardcoded defaults:

```
fast_window: 5
slow_window: 50, 200
```

That's 2 backtests. If they return **identical** numbers, the worker is ignoring `params` and using internal defaults — bug we'd need to fix in `services/backtest_worker/main.py`. If they return **different** numbers, params flow end-to-end and you can sweep with confidence.

## Guardrails

- **MAX_COMBOS = 50** — refuses to submit more than 50 backtests in one sweep
- **Parse errors shown inline** — won't submit with bad grid syntax
- **Polling** — refreshes every 3s while any sweep run is pending/running, then stops

## Known Limitations

- **No nav link** — must type `/backtests/sweep` URL directly. Can add to sidebar later.
- **Sweep state is in-memory only** — reload the page = lose the sweep view. The individual backtests are still in the database and viewable in the main list, but you lose the "which ones are part of this sweep" grouping. A future improvement would add a `sweep_id` column and persist this.
- **Cartesian product only** — no random sampling, latin hypercube, Bayesian optimization. Pure grid.
- **Numeric params only** — string params (e.g., `signal_type: "ema"`) not supported by the parser. Can extend if needed.
- **Single symbol per sweep** — multi-symbol sweeps not yet supported.

## What's Next After Tonight

- Add `sweep_id` column to backtests table → persistent sweep grouping
- Sidebar link to `/backtests/sweep`
- Walk-forward analysis (train/test split on time)
- Result export (CSV download of the table)
- Random/Bayesian search alternatives to grid
