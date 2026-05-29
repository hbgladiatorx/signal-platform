# Walk-Forward Stage 2 — FIX

The previous Stage 2 zip used an auth/data-fetching pattern that doesn't
exist in your project. This fix replaces the three page files with
versions that match your actual conventions:

- `useApi()` hook + `api.get<T>()` / `api.post<T>()`
- `@tanstack/react-query` for `useQuery` / `useMutation`
- `<AppShell title="…">` wrapper for nav
- `text-navy-700` for headings (matching your Tailwind palette)

The `frontend/lib/walkforward-types.ts` file from the previous zip is
unchanged and still correct — no need to touch it.

## Install

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step33-walkforward-frontend-fix.zip
git add -A
git commit -m "Walk-forward Stage 2: rewrite to match useApi/useQuery/AppShell pattern"
git push
```

## Deploy

```bash
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
docker compose logs --tail=30 frontend
```

Wait for `Ready in NNNms` then open
`https://signal.cimcha.com/walkforwards`. The list page should now
render with your existing SMACrossover walkforward row.
