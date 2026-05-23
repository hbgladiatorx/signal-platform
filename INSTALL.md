# Step 11 — Live WebSocket + Real-Time Chart

This archive contains:

**Backend (Python):**
- `services/api/redis_subscriber.py` — NEW: Redis stream subscriber background task
- `services/api/routers/ws.py` — NEW: WebSocket endpoint with first-message JWT auth
- `services/api/main.py` — REPLACED: now includes WS router + broadcaster lifecycle
- `services/api/routers/market.py` — REPLACED: adds /market/quotes/recent for chart history

**Frontend (TypeScript):**
- `frontend/package.json` — REPLACED: adds lightweight-charts dependency
- `frontend/lib/types.ts` — REPLACED: adds WS message types + QuoteChartPoint
- `frontend/lib/useWebSocket.ts` — NEW: WS hook with auth and reconnect
- `frontend/components/charts/PriceChart.tsx` — NEW: mid-price line chart
- `frontend/components/charts/LiveTrades.tsx` — NEW: live trade tape
- `frontend/app/instruments/[symbol]/page.tsx` — REPLACED: wires chart + tape + WS

## How to Apply

```bash
cd ~/signal-platform
unzip ~/Downloads/step11-live-data.zip
```

The archive layout mirrors the repo, so files land in place. Some
files have the `(REPLACED)` marker above — make sure the unzip
overwrites them. If your unzip prompts, answer "yes" (or `A` for All).

## After Unzipping

1. Verify the four backend files: `ls services/api/redis_subscriber.py services/api/routers/ws.py services/api/main.py services/api/routers/market.py`
2. Verify the frontend additions: `ls frontend/lib/useWebSocket.ts frontend/components/charts/`
3. Commit: `git add -A && git commit -m "Step 11: live WS + chart" && git push`
4. On the box: `git pull && docker compose build api frontend && docker compose up -d`
5. Visit `https://signal.cimcha.com/instruments/BTC-USDT@BINANCEUS` — you should see the chart load with the last hour of data, then a "Live" indicator and updates flowing in real-time.

## What's New In The UI

- **Live indicator badge** on the chart shows connection state (green pulse + "Live" / gray + "Disconnected")
- **Mid price line** auto-extends as new quotes arrive
- **Latest quote panel** updates without polling
- **Live tape** prepends new trades with a brief color flash (green for buy, red for sell)
