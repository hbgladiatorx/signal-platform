# Step 10 — Frontend Files

This archive contains all the frontend code for Step 10, plus the
updated `docker-compose.yml` and the new `frontend.Dockerfile`.

## How to Apply

Unzip this archive INTO your repo root (`~/signal-platform`). The
archive layout mirrors the repo layout, so files land where they
belong.

```bash
cd ~/signal-platform
unzip ~/Downloads/step10-frontend.zip
```

After unzipping, your repo will have:

```
signal-platform/
├── docker-compose.yml          # UPDATED — adds frontend service
├── frontend/                   # NEW — all Next.js code
│   ├── .env.example
│   ├── .eslintrc.json
│   ├── .gitignore
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── auth/callback/page.tsx
│   │   ├── dashboard/page.tsx
│   │   ├── instruments/page.tsx
│   │   ├── instruments/[symbol]/page.tsx
│   │   ├── strategies/page.tsx
│   │   ├── system/health/page.tsx
│   │   └── settings/page.tsx
│   ├── components/
│   │   ├── auth/
│   │   │   ├── AuthProvider.tsx
│   │   │   ├── LoginButton.tsx
│   │   │   ├── LogoutButton.tsx
│   │   │   └── ProtectedRoute.tsx
│   │   ├── forms/
│   │   │   ├── SchemaForm.tsx
│   │   │   └── schema-types.ts
│   │   └── nav/
│   │       ├── AppShell.tsx
│   │       ├── Header.tsx
│   │       └── Sidebar.tsx
│   └── lib/
│       ├── api.ts
│       ├── query.ts
│       ├── types.ts
│       ├── useApi.ts
│       └── utils.ts
└── infra/docker/
    └── frontend.Dockerfile     # NEW — multi-stage Next.js build
```

Note: `frontend.Dockerfile` ships at the archive root next to
docker-compose.yml. After unzipping, move it into `infra/docker/`:

```bash
mv frontend.Dockerfile infra/docker/frontend.Dockerfile
```

## What's Next

After unzipping, the steps Claude will guide you through:

1. Add the 5 NEXT_PUBLIC_* variables to your `.env` on the Lightsail box
2. `git add -A && git commit && git push` from your Mac
3. `git pull` and `docker compose up -d --build frontend caddy` on the box
4. Visit `https://signal.cimcha.com` — should show the login screen
5. Click Sign in, authenticate via Auth0, land at the dashboard
