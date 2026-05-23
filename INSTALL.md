# Step 17 — Bar API + Candlestick Chart

Files in this archive:

**Backend:**
- `services/api/routers/market.py` — REPLACED: adds `GET /market/bars` endpoint

**Frontend:**
- `frontend/lib/types.ts` — REPLACED: adds `Bar`, `BarResolution`, `BAR_RESOLUTIONS`, `RESOLUTION_SECONDS`
- `frontend/components/charts/PriceChart.tsx` — REPLACED: full candlestick chart with resolution selector, volume histogram, VWAP overlay, live trade updates

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step17-bars-chart.zip
git add -A
git commit -m "Step 17: bar API + candlestick chart"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
```

## Verify

1. Open `https://signal.cimcha.com/instruments/BTC-USDT@BINANCEUS`
2. Chart should show candlesticks (red/green) with volume histogram below
3. Click the **1m / 5m / 15m / 1h / 4h / 1d** buttons to switch resolution; chart re-fetches
4. Check the **VWAP** checkbox to overlay the orange VWAP line
5. The "Live" badge should be green and pulsing; new trades update the current bar's high/low/close in real-time
