# Step 26 — User Strategies Foundation

## What This Ships

Five files:

| File | Status | Purpose |
|------|--------|---------|
| `migrations/versions/0006_user_strategies.sql` | NEW | DB table for user-authored strategies |
| `packages/strategy/validator.py` | NEW | AST validator + restricted exec for params extraction |
| `packages/data/user_strategies.py` | NEW | DB layer (CRUD) |
| `services/api/deps.py` | REPLACES existing | Adds `get_current_user_record` + `CurrentUserRecord` for reuse |
| `services/api/routers/user_strategies.py` | NEW | API endpoints |

Plus one manual edit to `services/api/main.py` — see below.

This is **foundation only**. No LLM, no frontend UI, no worker integration yet:

- Step 27 adds worker integration (dynamic strategy loading from DB)
- Step 28 adds LLM translation endpoint
- Step 29 adds the frontend Monaco editor

You can use `POST /user-strategies` from `curl` today to validate the pipeline end-to-end.


## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step26-user-strategies.zip
git status
```

Expected `git status`:
- modified: `services/api/deps.py`
- new files: the four new ones

**Now manually edit `services/api/main.py`** to register the new router. Find the existing router includes (look for lines like `app.include_router(strategies.router)` or similar) and add a new line right after them. The exact change:

```python
# Find the existing import block of routers, e.g.:
from services.api.routers import (
    backtests,
    strategies,
    # ... other routers
)
# Add user_strategies to that import list.

# Then find the existing app.include_router(...) calls and add:
app.include_router(user_strategies.router)
```

If `services/api/main.py` imports routers individually instead, just add a matching import line + `include_router` call alongside the existing ones.

Then:

```bash
git add -A
git commit -m "Step 26: user strategies foundation (DB schema + API CRUD + AST validator)"
git push
```


## Deploy (Box)

```bash
cd ~/app
git pull

# Apply the migration
docker exec -i signal_postgres psql -U signal -d signal_platform < migrations/versions/0006_user_strategies.sql

# Verify the table was created
docker exec -i signal_postgres psql -U signal -d signal_platform -c "\d user_strategies"

# Rebuild and restart API
docker compose build api
docker compose up -d --force-recreate api

# Verify it came up clean
sleep 3
docker compose logs --tail=20 api | grep -v health
```


## Verify End-to-End

```bash
# Get a JWT (same as Step 23 tests)
JWT=$(curl -s -X POST https://cimcha-signal.us.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "GebwZSFIIUVwcq9zhy2Ev7EBmQ9Pbnyw",
    "client_secret": "LsDhK10Kpg4uM70FcjHv8lFCoAsJnUDiDW9WFaQAqjMSXBs70LNzF5un5hGT5m8Q",
    "audience": "https://signal.cimcha.com/api",
    "grant_type": "client_credentials"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test 1: validation endpoint with hostile input → should return ok=false
echo "=== Test 1: Hostile source ==="
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"source_code":"import os\nos.system(\"rm -rf /\")"}' \
  "https://signal.cimcha.com/api/user-strategies/validate" | python3 -m json.tool

# Test 2: validation endpoint with good source → should return ok=true
echo ""
echo "=== Test 2: Good source ==="
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d @- "https://signal.cimcha.com/api/user-strategies/validate" << 'JSON' | python3 -m json.tool
{"source_code": "from packages.strategy import Strategy, BarContext\nfrom packages.strategy.indicators import rsi\nfrom pydantic import BaseModel, Field\n\nclass MyParams(BaseModel):\n    period: int = Field(default=14, ge=2, le=100)\n\nclass MyStrategy(Strategy):\n    PARAMS_MODEL = MyParams\n    DESCRIPTION = 'test'\n    def __init__(self, symbols, params):\n        super().__init__()\n    def on_bar(self, ctx):\n        pass\n"}
JSON

# Test 3: create endpoint (saves to DB)
echo ""
echo "=== Test 3: Create user strategy ==="
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d @- "https://signal.cimcha.com/api/user-strategies" << 'JSON' | python3 -m json.tool
{
  "name": "TestStrategy",
  "description": "My first user strategy",
  "source_code": "from packages.strategy import Strategy, BarContext\nfrom packages.strategy.indicators import rsi\nfrom pydantic import BaseModel, Field\n\nclass MyParams(BaseModel):\n    period: int = Field(default=14, ge=2, le=100)\n\nclass MyStrategy(Strategy):\n    PARAMS_MODEL = MyParams\n    DESCRIPTION = 'test'\n    def __init__(self, symbols, params):\n        super().__init__()\n    def on_bar(self, ctx):\n        pass\n"
}
JSON

# Test 4: list
echo ""
echo "=== Test 4: List user strategies ==="
curl -s -H "Authorization: Bearer $JWT" \
  "https://signal.cimcha.com/api/user-strategies" | python3 -m json.tool
```


## What's Validated

The AST validator rejects (all unit-tested):

- Any import outside the allowlist (`packages.strategy`, `pydantic`, `typing`, `__future__`, `dataclasses`, `math`, `enum`)
- Calls to: `eval`, `exec`, `compile`, `__import__`, `open`, `input`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`, `breakpoint`, `help`
- Dunder attribute access (except a tiny whitelist needed for class definitions)
- `global` / `nonlocal` statements
- Sources that don't define exactly one Strategy subclass
- Strategy classes missing a `PARAMS_MODEL` attribute

If validation passes, the source is then executed in a restricted namespace (minimal builtins, controlled `__import__`) to extract the JSON Schema from the strategy's `PARAMS_MODEL`. That schema is persisted alongside the source so the frontend can render the params form without re-executing user code.


## Security Notes

- This is **single-user trust model**. The AST validator is defense-in-depth against your own mistakes and LLM hallucinations, not a hostile-actor sandbox.
- Real isolation (subprocess + rlimit + seccomp) comes in **Step 30** before you onboard others.
- The DB stores raw source code; if you change the validator later, existing rows are not retroactively re-validated. Add this as a future cleanup carryover.
