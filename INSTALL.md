# Step 23 — Backtest API Endpoints

Files in this archive:

- `services/api/routers/strategies.py` — NEW: GET /strategies, GET /strategies/{name}
- `services/api/routers/backtests.py` — NEW: POST/GET endpoints under /backtests
- `services/api/main.py` — UPDATED: includes the two new routers

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /strategies | List available strategies + JSON schemas |
| GET | /strategies/{name} | One strategy's info |
| POST | /backtests | Create + enqueue a new backtest |
| GET | /backtests | List my backtests (paginated) |
| GET | /backtests/{id} | Full backtest header + summary metrics |
| GET | /backtests/{id}/trades | Closed round trips |
| GET | /backtests/{id}/equity | Equity curve |

All require auth. `POST /backtests` and `GET /backtests*` require a user
record (look up by JWT sub); M2M tokens won't work unless you pre-provision
a `users` row for them.

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step23-backtest-api.zip
git add -A
git commit -m "Step 23: backtest + strategies API endpoints"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build api
docker compose up -d --force-recreate api
```

## Verify with the M2M Token

Quick check that the routes are registered and authenticated:

```bash
# Get a JWT (already memorized in earlier sessions)
JWT=$(curl -s -X POST https://cimcha-signal.us.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "GebwZSFIIUVwcq9zhy2Ev7EBmQ9Pbnyw",
    "client_secret": "LsDhK10Kpg4uM70FcjHv8lFCoAsJnUDiDW9WFaQAqjMSXBs70LNzF5un5hGT5m8Q",
    "audience": "https://signal.cimcha.com/api",
    "grant_type": "client_credentials"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Public endpoint (no user record needed)
echo "=== GET /strategies ==="
curl -s -H "Authorization: Bearer $JWT" \
  "https://signal.cimcha.com/api/strategies" | python3 -m json.tool

# User-scoped endpoint — should 404 because M2M tokens don't have a users row
echo "=== GET /backtests (expect 404: no user record for M2M) ==="
curl -s -w "\nHTTP %{http_code}\n" -H "Authorization: Bearer $JWT" \
  "https://signal.cimcha.com/api/backtests"
```

`GET /strategies` should return a JSON array with one entry (`SMACrossover`)
including its params schema.

`GET /backtests` will return 404 with a message explaining that M2M tokens
don't have a user record. That confirms auth flows and user lookup work.

## Verify via Real User Path (Optional)

To exercise the user-scoped endpoints end-to-end, sign in through the
frontend (which uses the Auth0 PKCE flow → user-scoped JWT → maps to your
users row). Then:

1. Open `https://signal.cimcha.com` and log in
2. Open browser DevTools → Network tab
3. Refresh — find the JWT in any `/api/me` call's Authorization header
4. Copy the JWT, then:

```bash
USER_JWT="<paste-here>"

curl -s -H "Authorization: Bearer $USER_JWT" \
  "https://signal.cimcha.com/api/backtests" | python3 -m json.tool
```

This should return the list of backtests we created in Steps 22a and 22b
(2 completed runs).

## Verify POST Workflow with M2M Shim

If you want to exercise the POST flow without UI, you can temporarily
insert a `users` row mapped to the M2M client_id, then POST. Cleanup
is your responsibility:

```sql
-- One-time: provision a users row for the M2M client (only for testing!)
INSERT INTO users (auth0_sub, email, role)
VALUES ('GebwZSFIIUVwcq9zhy2Ev7EBmQ9Pbnyw@clients', 'm2m-test@signal', 'admin')
ON CONFLICT (auth0_sub) DO NOTHING;
```

Then:

```bash
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "SMACrossover",
    "params": {"fast_period": 5, "slow_period": 20, "position_size": 0.001},
    "symbols": ["BTC-USDT@BINANCEUS"],
    "bar_resolution": "1h"
  }' \
  "https://signal.cimcha.com/api/backtests" | python3 -m json.tool
```

Note: Auth0's M2M `sub` claim format is typically `<client_id>@clients`.
If the example above 404s on user lookup, get the M2M token's `sub` value
by decoding the JWT first (e.g., paste into jwt.io) and use that.
