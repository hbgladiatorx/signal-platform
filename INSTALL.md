# Step 14 — Settings: Instruments + Data Sources

Files in this archive:

**Backend:**
- `services/api/routers/instruments.py` — REPLACED: adds POST and PUT endpoints

**Frontend:**
- `frontend/lib/types.ts` — REPLACED: adds `InstrumentCreate` and `VENUE_SCHEMAS`
- `frontend/components/settings/InstrumentsSection.tsx` — NEW
- `frontend/components/settings/DataSourcesSection.tsx` — NEW
- `frontend/app/settings/page.tsx` — REPLACED: 4 tabs

## Apply

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step14-instruments.zip
git add -A
git commit -m "Step 14: settings instruments + data sources tabs"
git push
```

## Deploy

```bash
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
```

No DB migration needed — we reuse the existing `instruments` table.

## Verify

1. Visit `https://signal.cimcha.com/settings`
2. Click the **Instruments** tab — see BTC-USDT and ETH-USDT with active toggles
3. Try toggling ETH-USDT to inactive, refresh — state persists
4. Click "+ Add instrument", try a known good pair like SOL-USDT, click Add
5. Backend verifies symbol against Binance.US exchangeInfo, then inserts
6. Try a bogus pair like "ABC-XYZ" → red error message
7. Click the **Data Sources** tab — see Binance.US listed as "Available" with active/inactive counts, Alpaca listed as "Coming soon"
