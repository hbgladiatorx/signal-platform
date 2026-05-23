# Step 13 — Settings: Profile + API Keys

Files in this archive:

**Migration:**
- `migrations/versions/0002_users_and_credentials.sql` — NEW: creates `users`, `user_preferences`, `api_credentials`

**Backend:**
- `packages/core/encryption.py` — NEW: Fernet wrapper for symmetric encryption at rest
- `services/api/routers/settings.py` — NEW: profile + API key endpoints
- `services/api/main.py` — REPLACED: registers the new settings router

**Frontend:**
- `frontend/lib/types.ts` — REPLACED: adds Profile, APICredential, ServiceSchema types
- `frontend/components/settings/ProfileSection.tsx` — NEW
- `frontend/components/settings/APIKeysSection.tsx` — NEW
- `frontend/app/settings/page.tsx` — REPLACED: tabbed UI

## Apply

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step13-settings.zip
```

## Step 1 — Apply the Migration

Run this on the Lightsail box (NOT your Mac) to create the new tables:

```bash
docker exec -i signal_postgres \
  psql -U signal -d signal_platform \
  < ~/app/migrations/versions/0002_users_and_credentials.sql
```

Expected output: `CREATE TABLE` (×3) and `CREATE INDEX` (×5) messages.

Verify:

```bash
docker exec -it signal_postgres \
  psql -U signal -d signal_platform \
  -c "\dt users user_preferences api_credentials"
```

Should show three new tables.

## Step 2 — Commit and Push (from Mac)

```bash
git add -A
git commit -m "Step 13: settings profile + encrypted API keys"
git push
```

## Step 3 — Deploy (on box)

```bash
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
```

Note: the migration in Step 1 must run BEFORE deploying the new API,
because the API code references the `users` table on every request.
If you deploy first the API will start but the settings endpoints will
500 until you run the migration.

## After Deploy — Verify in Browser

1. Visit `https://signal.cimcha.com/settings`
2. Profile tab: should show your email and Auth0 ID. Try updating display name and timezone, click Save. Saved.
3. API Keys tab: click "+ Add credential", choose Binance.US, type a label and two test values (you can use throwaway values like "test123" and "secret456" for now), click Save.
4. The credential should appear in the table with only the last 4 chars of the api_key visible.
5. Click Delete to remove it. Confirms then removes.

## Phase 2+ Note

Phase 4 (live trading) is where these credentials actually get used. The
execution engine will fetch the encrypted blob, decrypt at the moment of
use, sign the order request, and the plaintext never touches anything
that isn't on a hot code path.
