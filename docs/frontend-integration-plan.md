# thebayn frontend → signal-platform FastAPI integration plan

**Decision taken:** FastAPI backend is the source of truth. Frontend (`aliasfar7/thebayn`,
TanStack Start) rewires its data layer off Supabase/mocks onto the FastAPI API at
`https://signal.cimcha.com/api`. Plan-first — no code until this is approved.

---

## 0. The two big mismatches (read first)

The frontend is **not** the backend's UI with a different coat of paint. Two structural gaps
dominate the effort:

### A. Identity provider mismatch
- **Frontend** authenticates with **Supabase Auth** (email/pw + Google OAuth, sessions, JWTs).
- **Backend** authenticates with **Auth0** RS256 JWTs (`AUTH0_DOMAIN`/`AUTH0_AUDIENCE`,
  JWKS-verified), resolves `sub` → `users` row, scopes every query by `user_id`.
- These don't talk to each other. Resolution options:
  - **(Recommended) Teach FastAPI to verify Supabase JWTs.** Supabase already issues a signed
    JWT per session. Add a verifier in `services/api/auth.py` that accepts Supabase tokens
    (verify via Supabase JWKS / project JWT secret), map Supabase `sub` (the user UUID) into the
    `users` table the same way Auth0 `sub` is mapped today. Frontend keeps its existing Supabase
    login UX untouched; it just forwards `session.access_token` as `Authorization: Bearer`.
  - **(Alternative) Migrate the frontend to Auth0.** Rip out Supabase auth, add Auth0 SPA SDK.
    More frontend churn, loses the already-built auth/onboarding/reset flows.
- **This is the first decision needed.** Recommend the verifier path.

### B. Domain-model mismatch — frontend is a 2-sided marketplace, backend is a 1-user workbench
- **Backend has (maps cleanly):** user strategies (Python source), backtests (+ trades, equity,
  attribution, ml_model), walk-forwards, ML training store, paper/live sessions, instruments,
  market data, settings/profile, API credentials, kill-switch.
- **Backend does NOT have (greenfield):** signal **products** (marketplace listings),
  **product_subscriptions**, **published/personal signals feed**, **taken_signals**,
  **earnings/payouts**, **billing tiers/add-ons/plan_state**. The frontend's entire consumer
  (`app.*`) surface assumes these.
- So "adapt to backend" splits into **(1) wire the studio/developer surface to existing
  endpoints** (mostly straightforward) and **(2) build new backend domain + endpoints for the
  consumer marketplace** (substantial new backend work).

### C. Sub-gap: visual graph ↔ runnable strategy
- Frontend strategies are **visual `StrategyGraph`** (reactflow nodes/edges), built by
  `agent.ts` from prompts client-side.
- Backend strategies are **Python source** (`user_strategies.source_code`, AST-validated) or
  built-in registry classes. It has `/user-strategies/translate` (LLM NL→Python).
- There is **no graph→Python compiler** on either side. Bridging requires one of:
  - serialize the graph to a deterministic Python emitter (most work, most control),
  - treat the graph as a *view* and drive persistence via the NL→code `/translate` path
    (reuse what exists; graph becomes advisory), or
  - store the graph JSON on the strategy row and compile at run time (needs a new backend
    graph-interpreter strategy).
- **Second decision needed.** Recommend: short-term reuse `/translate`; store graph JSON
  alongside for round-tripping; build a real graph-compiler later.

---

## 1. Endpoint-by-route / function mapping

### Studio / developer surface (maps to EXISTING backend) — Phase 2

| Frontend (`studio.ts` / route) | Backend endpoint | Notes / gap |
|---|---|---|
| `getDevStrategies()` | `GET /user-strategies` | shape: DevStrategy ← UserStrategySummary. graph not stored yet. |
| `getDevStrategy(id)` | `GET /user-strategies/{id}` | returns source_code; need graph round-trip (see C). |
| `ensureDevStrategyDraft()` / `saveStrategyGraph()` | `POST` / `PUT /user-strategies` | needs graph→code bridge (C). Persist graph JSON (new column or params). |
| `getTemplates()` (stub) | `GET /strategies` (built-in) | use built-ins as templates. |
| `runBacktest()` | `POST /backtests` then poll `GET /backtests/{id}` | map params: capital→starting_cash, commissionBps→fee_rate_bps, slippageBps→slippage_bps. |
| `getBacktestsForStrategy()` | `GET /backtests?` (filter by strategy) | backend lists by user; add strategy filter or filter client-side. |
| `getBacktest(id)` | `GET /backtests/{id}` (+ `/trades`, `/equity`) | BacktestRun ← BacktestDetail+trades+equity. Stat-name remap. |
| ML page / `studio.signals` | `GET /ml/strategies`, `POST /ml/strategies/{name}/train`, `GET /ml/strategies/{name}/model` | already exists; thebayn ML UI to be added. |
| (new) walk-forward UI | `POST/GET /walkforwards` | optional, backend ready. |
| `deployStrategyLive()` (stub) | `POST /paper-sessions` | needs api_credential_id (from settings). |
| `getPersonalSignals()` (stub) | — | needs published-signals backend (Phase 3). |
| `getEarnings()` (stub) | — | greenfield (Phase 4). |
| `submitStrategyToBayn()` (stub) | — | needs submissions/marketplace (Phase 3/4). |

### Consumer surface (`trader.ts`) → mostly GREENFIELD backend — Phase 3

| Frontend (`trader.ts`) | Current source | New backend needed |
|---|---|---|
| `getCatalog()` / `getProduct()` | Supabase `signal_products` | `GET /products`, `GET /products/{id}` + `signal_products` table. |
| `getMySubscriptions()` / `isSubscribed()` / `subscribe`/`unsubscribe` | Supabase `product_subscriptions` | `/subscriptions` CRUD + table. |
| `getRecentSignals()`/`getSignal()`/`getOpenSignals()`/`getSignals()` | Supabase `signals` | `GET /signals` + published-signals table fed by live sessions. |
| `getTakenSignals()` / `markSignalTaken()` | Supabase `taken_signals` | `/taken-signals` + table. |
| `getStrategyEquity()` / `getUserPerformance()` | Supabase aggregation | `GET /performance` (server-computed). |
| `getUserPreferences()` / `update` | Supabase `user_preferences` | backend `user_preferences` table EXISTS → add `/settings/preferences` get/put. |
| `getPlanState()` | Supabase `plan_state` | tie to billing (Phase 4). |
| `subscribeToSignals()` / realtime | Supabase realtime | backend `/ws` websocket (exists) → add a signals channel. |
| `sendOrderToBroker()` (stub) | — | `POST /paper-sessions/{id}/...` or new order route. |

### Cross-cutting

| Frontend | Backend |
|---|---|
| auth (`use-auth.ts`, `auth.tsx`) | keep Supabase login; forward token → FastAPI (decision A). On login: `POST/GET /settings/profile` to upsert user. |
| `billing.ts` (localStorage tiers/addons) | greenfield `/billing` + tables (Phase 4). Keep mocked until then. |
| `finnhub.functions.ts` (quotes/news) | keep as-is OR move quotes to `GET /market/*`; news has no backend equiv → keep Finnhub. |
| `agent.ts` `chatStudioAI`/`buildGraphFromPrompt` | wire to `POST /user-strategies/translate` (real LLM). Trader AI chat = greenfield. |
| settings API keys | `GET/POST/DELETE /settings/api-keys` (exists). |

---

## 2. Backend gaps to build (new work, FastAPI-as-truth)

1. **Supabase JWT verification** in `services/api/auth.py` (+ user mapping). *(Phase 1)*
2. **`/settings/preferences`** GET/PUT over existing `user_preferences`. *(Phase 1, small)*
3. **Graph storage + bridge**: column `graph_json` on `user_strategies` (or reuse params), plus
   the graph→code strategy chosen in (C). *(Phase 2)*
4. **Backtest list filter by strategy** (query param). *(Phase 2, small)*
5. **Marketplace domain** (migrations + routers): `signal_products`, `product_subscriptions`,
   published `signals`, `taken_signals`; routers `/products`, `/subscriptions`, `/signals`,
   `/taken-signals`, `/performance`. *(Phase 3, large)*
6. **Live signal publishing**: paper/live sessions emit published signals → table + `/ws`
   channel the frontend subscribes to. *(Phase 3)*
7. **Billing & earnings**: tiers/add-ons/plan_state/earnings tables + `/billing` + payment
   provider (Stripe). *(Phase 4, large)*
8. **CORS**: set `CORS_ORIGINS` to the deployed thebayn origin (currently `*`). *(Phase 1)*

---

## 3. Frontend changes (per phase)

- **P1:** add `src/lib/api/client.ts` (fetch wrapper: base URL from `VITE_API_BASE`, inject
  Supabase `access_token` as Bearer, error mapping). Add `.env` `VITE_API_BASE`. Keep Supabase
  client for auth only.
- **P2:** rewrite `studio.ts` (and the studio routes' hooks) to call the client → backtests,
  user-strategies, ml, walkforwards. Add ML + (optional) walk-forward UI. Map stat/field names.
  Wire `chatStudioAI` → `/translate`.
- **P3:** rewrite `trader.ts` to the new marketplace endpoints; swap Supabase realtime →
  backend `/ws`.
- **P4:** replace `billing.ts` localStorage with `/billing`; wire earnings.

---

## 4. Recommended migration order

1. **Phase 1 — Foundation:** auth bridge (decision A), API client, user provisioning,
   `/settings/preferences`, CORS. *Nothing user-visible changes yet; proves the token path.*
2. **Phase 2 — Studio:** wire developer surface to existing backtest/strategy/ML/walk-forward
   endpoints + graph bridge (decision C). *Highest value, lowest backend risk — leverages the
   Phase 2–4 backend just committed.*
3. **Phase 3 — Consumer marketplace:** build greenfield backend domain + wire `trader.ts`.
   *Largest new-backend effort.*
4. **Phase 4 — Billing/earnings:** monetization. *Can stay mocked until last.*

---

## 5. Decisions — LOCKED (2026-06-04)
1. **Auth:** ✅ FastAPI verifies Supabase JWTs. Frontend keeps Supabase login; forwards
   `session.access_token` as Bearer. Backend gets a Supabase-token verifier + `sub`→`users` map.
2. **Graph↔code:** ✅ Reuse `POST /user-strategies/translate` (LLM NL→Python) short-term; store
   the graph JSON alongside for round-tripping. Real graph→Python compiler deferred.
3. **Marketplace scope:** ✅ Deferred. Ship Phases 1+2 (foundation + studio on existing
   endpoints) first; consumer marketplace stays mocked until later.
4. **Deploy target:** ✅ Same Lightsail box behind Caddy. thebayn served on signal.cimcha.com,
   API at `/api`. `VITE_API_BASE=/api` (same origin → CORS stays simple).

## 6. Locked near-term scope (Phases 1–2 only)
**Phase 1 — Foundation:** Supabase JWT verifier in `services/api/auth.py` (+ user mapping);
`src/lib/api/client.ts` (Bearer-injecting fetch wrapper, `VITE_API_BASE=/api`); user
provisioning via `/settings/profile` on login; `/settings/preferences` GET/PUT over existing
`user_preferences`; Caddy route for thebayn; CORS confirm.
**Phase 2 — Studio:** rewrite `studio.ts` + studio routes onto `/user-strategies`, `/backtests`
(+`/trades`,`/equity`), `/ml/*`, `/walkforwards`; add `graph_json` to `user_strategies`;
`chatStudioAI`→`/translate`; settings (profile + api-keys) wired. Marketplace `trader.ts`,
billing, earnings remain mocked.
