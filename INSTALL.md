# Step 24 — Strategies + Backtests Frontend

Files in this archive:

- `frontend/lib/backtest-types.ts` — NEW: TypeScript types matching the API contracts
- `frontend/app/strategies/page.tsx` — REPLACED: was a "Phase 2 placeholder", now a real strategy browser
- `frontend/app/backtests/page.tsx` — NEW: list of user's backtests with status badges, auto-refresh
- `frontend/app/backtests/new/page.tsx` — NEW: configuration form, submits via POST

## What This Ships

1. **`/strategies`** — discovers available strategies, displays each as a card with params
2. **`/backtests`** — table view of past runs, status badges, auto-refreshes every 3s while runs are active
3. **`/backtests/new`** — form for picking strategy + symbols + resolution + cash/fees, submits and redirects to list

Backtest detail page (with equity-curve chart) is Step 25.

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step24-frontend.zip
git status
git add -A
git commit -m "Step 24: strategies page + backtests list + new backtest form"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
```

This rebuilds the Next.js bundle. About 60-90 seconds.

## Verify

Open in your browser:

1. **`https://signal.cimcha.com/strategies`** — should show one strategy card (SMACrossover) with three parameters listed and their default/min/max values.

2. **`https://signal.cimcha.com/backtests`** — should show 3-4 prior backtests with metrics. Pending/running ones will auto-refresh.

3. **`https://signal.cimcha.com/backtests/new`** — should show the form:
    - Strategy dropdown (with SMACrossover preselected since only one)
    - 3 parameter inputs (fast_period, slow_period, position_size) with defaults from the schema
    - Symbol multi-select listing your active instruments
    - 6 resolution buttons (1h highlighted by default)
    - 3 execution config fields (cash, fee, slippage)
    - Submit button

4. **Fill in valid values and submit** — should redirect to `/backtests` and show your new row at the top (initially pending, then completing within a few seconds).

5. **Try submitting invalid params** (e.g., slow_period < fast_period) — should display a server error from the API's 422 response under the form.

## Known Issue (Will Fix in Step 25)

The list page links each row to `/backtests/{id}` but that page doesn't exist yet — clicking will 404. Step 25 builds the detail page.
