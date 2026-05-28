# Where to host this and how to wire the backend

Short answer: **don't move to Lightsail.** Keep Lovable as the frontend editor, push to GitHub, deploy to **Vercel**, and use **Supabase** (hosted) as the database + auth + storage. All the "backend" code lives inside this same TanStack Start app as server functions — you don't need a separate Express/Node server on Ubuntu.

---

## Why not AWS Lightsail

Lightsail = a raw Ubuntu VM. You'd have to:
- run Node/PM2/Nginx yourself
- configure HTTPS + auto-renew certs
- handle deploys (CI/CD, zero-downtime restarts)
- patch the OS
- size and pay for it even when idle

TanStack Start is built for serverless edge runtimes (Vercel, Netlify, Cloudflare). You'd be fighting the framework on a VM. Lightsail makes sense only if you need a long-running custom daemon — you don't.

## Recommended stack

```text
Lovable (edit frontend)
   │  git commit
   ▼
GitHub repo  ─────────►  Vercel  (auto-deploy on push)
                            │
                            ▼
                     Supabase (DB + Auth + Storage + Realtime)
```

- **Lovable** → visual edits, AI scaffolding
- **GitHub** → source of truth, lets you also edit in Cursor/VS Code locally
- **Vercel** → hosting, SSL, preview URLs per PR, zero config
- **Supabase** → Postgres + Auth + Storage + Row Level Security + Realtime, all behind one client SDK

You already have GitHub sync available in Lovable — flip it on and you're done with step 1.

## Where "the backend" actually lives

You do **not** need a separate backend project. TanStack Start has two server primitives that ship inside this same repo and deploy with the frontend:

1. **`createServerFn`** — typed RPC functions you call from the React app
   - `src/lib/*.functions.ts`
   - perfect for: fetching from DB, writing data, calling third-party APIs with secret keys, business logic
2. **Server routes** — `src/routes/api/*.ts`
   - perfect for: webhooks (Stripe, etc.), public REST endpoints, cron targets

Both run on Vercel's serverless/edge runtime automatically — no DevOps.

For Supabase you get three pre-wired clients:
- `@/integrations/supabase/client` — browser, respects RLS
- `requireSupabaseAuth` middleware — server fns acting as the logged-in user
- `@/integrations/supabase/client.server` — server-only admin client (bypasses RLS, for webhooks/cron only)

## How auth + data will work end to end

Your current `/auth` page already has the form. Once Supabase is wired:
1. Form calls `supabase.auth.signInWithPassword(...)` (or Google via Lovable's broker)
2. A root `onAuthStateChange` listener invalidates the router/cache
3. Protected routes live under `src/routes/_authenticated/*`
4. Server functions use `requireSupabaseAuth` and Postgres RLS enforces per-user access
5. Strategies, signals, backtests etc. become Postgres tables with RLS policies

## Recommended path forward (in order)

1. **Enable GitHub sync** in Lovable → pick a repo
2. **Sign up for Vercel** → "Import Git Repository" → pick that repo → deploy. Done. You now get a live URL on every push.
3. **Decide on Supabase**:
   - Easiest: enable **Lovable Cloud** here — it provisions a Supabase project for you and auto-injects every env var, generated client, and auth helper. You can later "eject" to your own Supabase if needed.
   - Or: create your own Supabase project, paste `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` into Vercel env vars (and into Lovable's secrets if you want to keep editing here).
4. **Model the data** in Supabase (tables: `profiles`, `strategies`, `subscriptions`, `signals`, `backtests`, …) with RLS policies scoped to `auth.uid()`
5. **Replace the mocked `/auth` submit** with a real `supabase.auth.*` call (and wire Google via Lovable's broker if you want OAuth)
6. **Replace the mock catalog/signals data** with server functions that query Supabase
7. **For paid plans** on `/pricing` — add Stripe via webhook server route (`src/routes/api/public/stripe-webhook.ts`)

## When you'd actually edit "locally on Ubuntu"

You don't need a server for this. After step 1:
```text
git clone <your-repo>          # on your laptop, not Lightsail
bun install
bun run dev
```
Edit in Cursor/VS Code, push, Vercel redeploys, Lovable picks up the same commits. Lovable + Cursor + Vercel all read/write the same git history.

## TL;DR recommendation

> **Lovable → GitHub → Vercel → Supabase.** Skip Lightsail. All backend logic stays inside this same TanStack Start app via `createServerFn` and server routes. Start by enabling Lovable Cloud (fastest path to a real DB + auth + storage), and turn on GitHub sync so you can also edit in Cursor whenever you want.

If you approve, the next build-mode steps would be: enable Lovable Cloud, wire the real auth flow on `/auth`, and design the first tables (`profiles`, `strategies`, `subscriptions`).
