# Step 19 — Strategy Framework

Files in this archive:

**Framework (packages/strategy):**
- `packages/strategy/__init__.py` — NEW: re-exports public API
- `packages/strategy/base.py` — NEW: `Strategy[P]` abstract class, `Order`, enums
- `packages/strategy/context.py` — NEW: `BarContext` — strategy's typed view of state
- `packages/strategy/indicators.py` — NEW: SMA, EMA, RSI, ATR over pandas
- `packages/strategy/registry.py` — NEW: discover strategies in `strategies/` dir

**Strategies dir:**
- `strategies/__init__.py` — NEW: package marker
- `strategies/sma_crossover.py` — NEW: example SMA crossover strategy

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step19-strategy-framework.zip
git add -A
git commit -m "Step 19: strategy framework + SMA crossover example"
git push
```

## Verify (Box) — No Deploy Needed

Step 19 ships framework code only. No services touched. We verify by
running a small Python session inside the API container, which already
has the dependencies we need.

```bash
cd ~/app
git pull
docker exec -it signal_api python3 << 'EOF'
from pathlib import Path
from packages.strategy.registry import discover_strategies

strats = discover_strategies(Path("/app/strategies"))
print(f"Discovered: {list(strats.keys())}")

if "SMACrossover" in strats:
    sma = strats["SMACrossover"]
    print(f"Description: {sma.description()}")
    print(f"Params schema fields: {list(sma.PARAMS_MODEL.model_fields.keys())}")
    # Instantiate with default params
    p = sma.PARAMS_MODEL()
    s = sma(symbols=["BTC-USDT@BINANCEUS"], params=p)
    s.on_init()
    print(f"Instantiated OK. State: {s.state}")
EOF
```

Expected output: `Discovered: ['SMACrossover']` and then descriptions of
the strategy. If you see this, the framework is loaded correctly inside
the running platform.

## What's Next (Step 20)

Step 20 builds the backtest engine: takes a Strategy + historical bars +
starting cash and replays them, simulating fills, tracking position and
equity. The output of Step 20 is a `BacktestResult` object (trades, equity
curve, P&L). No DB or worker yet — that's Step 22.
