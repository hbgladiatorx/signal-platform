# Step 27 — Worker Dynamic Loader + Merged Strategies Endpoint

## What This Ships

Three new files, two replaced files, and a Python patch script:

| File | Status | Purpose |
|------|--------|---------|
| `packages/strategy/validator.py` | REPLACES Step 26 version | Renames `_build_safe_builtins` → `build_safe_builtins` and `_safe_import` → `safe_import` (public) so the loader can reuse them |
| `packages/strategy/loader.py` | NEW | Compiles user source in restricted env and returns the Strategy class |
| `packages/strategy/resolver.py` | NEW | Async resolution: built-in registry first, then user_strategies DB |
| `services/api/routers/strategies.py` | REPLACES | `/strategies` returns built-ins + the user's own strategies, with a `source: "built-in" \| "user"` field |
| `services/api/routers/user_strategies.py` | REPLACES Step 26 version | Adds collision check: reject names that match a built-in strategy |
| `apply_step27_patches.py` | NEW (run once, then delete) | Surgically patches `backtests.py` (POST handler uses resolver) and `backtest_worker/main.py` (job processing uses resolver) |


## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step27-worker-resolver.zip

# Apply the in-place patches to backtests.py and the worker
python3 apply_step27_patches.py

# Expected output:
#   Patching services/api/routers/backtests.py …
#     [backtests.py imports] OK — applied
#     [backtests.py POST lookup] OK — applied
#   Patching services/backtest_worker/main.py …
#     [worker imports] OK — applied
#     [worker lookup] OK — applied
#   Done. 4 change(s) applied.

# Verify the changes look right
git diff services/api/routers/backtests.py services/backtest_worker/main.py

# Sanity: at least a handful of lines added in each
git diff --stat

# Clean up the patch script (it's idempotent, but no need to keep it)
rm apply_step27_patches.py

git status
git add -A
git commit -m "Step 27: worker dynamic loader + merged strategies endpoint"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull

# Rebuild the API AND the worker — both got new imports
docker compose build api backtest_worker
docker compose up -d --force-recreate api backtest_worker

# Verify clean startup
sleep 5
docker compose logs --tail=20 api | grep -v health | tail -15
echo "---"
docker compose logs --tail=20 backtest_worker | tail -15
```

Look for:
- API startup with `api.ready` and no traceback
- Worker startup with `backtest_worker.starting` listing the built-in strategies

If either crashes on import, the patch script may have misfired — paste me the traceback.

## Verify End-to-End

```bash
JWT=$(curl -s -X POST https://cimcha-signal.us.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "GebwZSFIIUVwcq9zhy2Ev7EBmQ9Pbnyw",
    "client_secret": "LsDhK10Kpg4uM70FcjHv8lFCoAsJnUDiDW9WFaQAqjMSXBs70LNzF5un5hGT5m8Q",
    "audience": "https://signal.cimcha.com/api",
    "grant_type": "client_credentials"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test 1: GET /strategies now includes the TestStrategy you created in Step 26
echo "=== /strategies should show TWO entries: SMACrossover + TestStrategy ==="
curl -s -H "Authorization: Bearer $JWT" \
  "https://signal.cimcha.com/api/strategies" | python3 -m json.tool

# Test 2: try to name a user_strategy after a built-in — should 409
echo ""
echo "=== Create with colliding name (expect 409) ==="
curl -s -w "\nHTTP %{http_code}\n" -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"SMACrossover","source_code":"x = 1"}' \
  "https://signal.cimcha.com/api/user-strategies"

# Test 3: actually RUN the TestStrategy via /backtests
echo ""
echo "=== Run backtest with the TestStrategy (user-authored) ==="
NEW_BT=$(curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "TestStrategy",
    "params": {"period": 14},
    "symbols": ["BTC-USDT@BINANCEUS"],
    "bar_resolution": "1h"
  }' \
  "https://signal.cimcha.com/api/backtests")
echo "POST response: $NEW_BT"
NEW_ID=$(echo "$NEW_BT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

sleep 5

echo ""
echo "=== Check status of the user-strategy backtest ==="
curl -s -H "Authorization: Bearer $JWT" \
  "https://signal.cimcha.com/api/backtests/$NEW_ID" | python3 -m json.tool | head -25

# Test 4: run a backtest with an unknown strategy — expect 422
echo ""
echo "=== Backtest with unknown strategy (expect 422) ==="
curl -s -w "\nHTTP %{http_code}\n" -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "DefinitelyNotAStrategy",
    "params": {},
    "symbols": ["BTC-USDT@BINANCEUS"],
    "bar_resolution": "1h"
  }' \
  "https://signal.cimcha.com/api/backtests"
```

## What's Tested

| Test | What it proves |
|------|----------------|
| `GET /strategies` returns user's TestStrategy alongside built-ins | Merged listing works |
| 409 on colliding name | Collision check at create works |
| POST /backtests with user-authored strategy succeeds | API resolver works |
| Backtest completes with status=completed | Worker resolver + loader work |
| 422 on unknown strategy | Error path works |

## Notes

- The TestStrategy created in Step 26 doesn't actually do anything meaningful (its `on_bar` is `pass`), so the backtest will complete with zero trades and zero return. The point is that it RUNS without raising NameError or some other module-not-loaded error.
- The Strategy class's `on_bar` is abstract on the base class but the TestStrategy's `pass` implementation satisfies the abstract requirement.
