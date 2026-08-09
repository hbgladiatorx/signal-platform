# Bayn Studio (thebayn) — implementation handoff

**For:** `aliasfar7` (owner of `aliasfar7/thebayn`, the TanStack Start frontend served at `signal.cimcha.com`)
**Backend:** `hbgladiatorx/signal-platform` (FastAPI) — fully consolidated on `main`, including the new `DELETE` endpoints referenced below.

Two features are requested in the Studio UI:

1. Make the **My Studio** status cards (Draft / Backtesting / Forward-testing / Live / Submitted) **clickable** → open the Strategies list filtered to that stage.
2. Add **Delete** (and confirm **Edit**) on **strategies**, and **Delete** on **backtests / walk-forwards**.

`thebayn` is a separate repo under a different owner, so it must be worked on **from its own repo** — not the `signal-platform` session.

---

## A. Getting set up — step by step (run these commands)

> Prereqs: `git`, and `bun` (TanStack Start apps build with bun). Install bun if needed: `curl -fsSL https://bun.sh/install | bash`

```bash
# 1. Clone the frontend repo
git clone https://github.com/aliasfar7/thebayn.git
cd thebayn

# 2. Install dependencies
bun install

# 3. Look at the available scripts (dev/build/start names vary)
cat package.json | grep -A20 '"scripts"'

# 4. Point the app at the API. Check for an example env file and copy it:
ls -a | grep -i env
cp .env.example .env 2>/dev/null || true
#    Then set the API base URL in .env to the FastAPI backend, e.g.:
#      VITE_API_BASE=https://signal.cimcha.com/api      (prod)
#      or  http://localhost:8000                        (local backend)
#    (Use whatever the codebase already calls it — grep for it:)
grep -rInE "API_BASE|apiBase|BASE_URL|/api" src app 2>/dev/null | head

# 5. Run the dev server (use the script name from step 3, usually one of:)
bun run dev        # or: bun dev  /  bun run start

# 6. Create a working branch before editing
git checkout -b feat/studio-cards-and-crud
```

### Optional: let Claude Code do the edits
Open a **new Claude Code session with `aliasfar7/thebayn` as the source repo**, then paste sections B–D of this file. Claude already knows the `signal-platform` API (below), so it can wire the calls directly. (It cannot be done from the `signal-platform` session — cross-owner repos can't be mixed in one session.)

---

## B. Feature 1 — clickable status cards

The dashboard already renders the counts and the Strategies page already has an "All stages" filter. So:

1. Wrap each stat card (Draft / Backtesting / Forward-testing / Live / Submitted) in a link to the Strategies route with a `stage` query param, e.g. `/studio/strategies?stage=live`.
2. On the Strategies page, read `?stage=` on load and set the stage filter to it (fall back to "All stages" when absent).

This is pure frontend — the strategy list data already loads; you're just filtering it. The **stage/status** value lives in `thebayn`'s own data, not in a `signal-platform` endpoint.

---

## C. Feature 2 — Delete / Edit

### Strategies (`/studio/strategies`)
- **Edit** already exists (keep it). It uses:
  - `GET  /user-strategies/{id}` — load source/metadata
  - `PUT  /user-strategies/{id}` — save `{ name, description, source_code }`
- **Add Delete** for **user-authored** strategies only (built-ins are shipped code, not deletable):
  - `DELETE /user-strategies/{id}` → `204` (owner-scoped soft-delete)
  - Gate the button on the strategy being user-owned; refresh the list on success.

### Backtests
- **Delete:** `DELETE /backtests/{id}` → `204` (cascades to its trades + equity). *(Added to `main`.)*
- **"Edit" = clone & re-run** (a run is an immutable record): `POST /backtests` with the same config to launch a fresh run.

### Walk-forwards
- **Delete:** `DELETE /walkforwards/{id}` → `204`. *(Added to `main`.)*

All deletes return **404** for a missing or another user's row (existence is never revealed).

---

## D. API reference (signal-platform `main`, all JWT-authenticated)

| Area | Endpoints |
|---|---|
| Strategies | `GET /strategies` · `GET/POST /user-strategies` · `GET/PUT/DELETE /user-strategies/{id}` · `POST /user-strategies/translate` · `POST /user-strategies/plan-graph-from-code` |
| Backtests | `GET/POST /backtests` · `GET /backtests/{id}` (+ `/trades`, `/equity`) · **`DELETE /backtests/{id}`** · `POST /backtests/{id}/narrative` · `POST /backtests/{id}/suggest-tweaks` |
| Walk-forwards | `GET/POST /walkforwards` · `GET /walkforwards/{id}` · **`DELETE /walkforwards/{id}`** |
| Market / instruments | `GET /market/bars` · `GET /instruments` · `POST /instruments/sync/binanceus` |
| ML / copilot / paper / live | `GET /ml/...` · `POST /copilot/...` · `paper_sessions` router · `live` router |

Auth: send the user's bearer token (`Authorization: Bearer <jwt>`) — same flow the rest of the Studio already uses.

---

## E. Commit & open a PR (step by step)

```bash
# after making the edits
git add -A
git commit -m "Studio: clickable status cards + strategy/backtest delete"
git push -u origin feat/studio-cards-and-crud

# then open a PR on GitHub:
#   https://github.com/aliasfar7/thebayn  ->  "Compare & pull request"
```

### Deploying (on the server, once merged)
`thebayn` is built alongside the backend via `signal-platform`'s `docker-compose.yml` (the `thebayn` service builds from `../thebayn`) and served by Caddy at `signal.cimcha.com`. So on the deploy box:

```bash
cd /home/signal/app        # the dir that holds docker-compose.yml
git -C ../thebayn pull     # pull the merged frontend (adjust path to where thebayn is checked out)
docker compose up -d --build thebayn
```
