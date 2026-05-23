# Step 12 — System Health Page

Files in this archive:

**Backend:**
- `services/api/routers/system.py` — NEW: /system/health/detail endpoint
- `services/api/main.py` — REPLACED: registers the new system router

**Frontend:**
- `frontend/lib/types.ts` — REPLACED: adds SystemHealthDetail types
- `frontend/app/system/health/page.tsx` — REPLACED: full ops dashboard

## Apply

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step12-system-health.zip
```

## Deploy

```bash
git add -A
git commit -m "Step 12: system health dashboard"
git push
```

Then on the Lightsail box:

```bash
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
```

Then visit https://signal.cimcha.com/system/health
