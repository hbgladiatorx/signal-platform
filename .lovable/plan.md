# Live data + onboarding-driven customization

## 1. Finnhub integration (live market + news)

New server functions in `src/lib/api/finnhub.functions.ts`:
- `validateTicker(symbol)` → `/search` then `/quote`; returns `{ valid, symbol, description, exchange, assetClass }`. Used inline in onboarding + Customize when adding tickers — invalid symbols are rejected at the input.
- `getQuotes(symbols[])` → batched `/quote` calls, returns price/change/percent. Powers ticker tape + Market Overview.
- `getCompanyNews(symbol, from, to)` and `getMarketNews(category)` → powers Market Wire and per-ticker news.
- 60s in-memory cache per symbol to stay inside free-tier limits.

Server-only — uses `process.env.FINNHUB_API_KEY`. Client calls via `useServerFn` + TanStack Query (cache 30–60s, refetch on focus).

Replace these mock readers:
- `getMarketOverview` / `marketTiles` → live quotes for watched tickers.
- `MarketTicker` / ticker tape → live quotes.
- `getMarketNews` / `marketNews` mock → Finnhub general + per-ticker news, filtered by enabled asset classes + "only watched tickers" toggle.

## 2. Onboarding becomes the customization flow

Rewrite `src/routes/onboarding.tsx` as a stepper that mirrors your checklist. Every step writes directly to the same `user-prefs` keys the live app already reads. All steps skippable except path, identity essentials, and plan.

**Shared:** path (trader/dev/both) → identity (display name, tz auto-detect, currency) → experience profile.

**Trader branch:** asset classes (required ≥1) → watched tickers per class (Finnhub-validated, suggested chips not pre-checked) → news sources + topics + "only watched" toggle → account size + risk % → home layout + visible sections → notifications → optional broker/agent hooks → "first action" landing choice.

**Dev branch:** studio plan → builder experience + AI preference → asset focus → workspace defaults (view, default asset class) → payout preference (placeholder) → first-strategy fork (template / AI / blank).

**Both:** trader branch full → condensed studio branch → `defaultModeOnLogin`.

Progress is persisted per step so "save & exit" resumes. Post-onboarding, skipped items surface as a dismissible checklist card on `/app/home` and `/studio/home`.

## 3. Remove Customize tab, add Customize button

- Delete the standalone customize tab navigation entry in `AppShell`.
- Keep the route `/app/customize` reachable as a "tweak" surface only — opened via a new "Customize" button in the Home header.
- Studio gets the same: `/studio/customize` button on `/studio/home`.

## 4. Strip Studio bare (no mock data)

`src/lib/api/studio.ts` returns empty arrays until the dev creates real strategies. All Studio pages keep their routes but render empty states with CTAs:
- `/studio/strategies` → "No strategies yet — start in the builder".
- `/studio/backtests`, `/studio/submissions`, `/studio/earnings`, `/studio/signals` → empty states.
- `/studio/home` → welcome checklist from onboarding answers.

Mock arrays in `src/lib/mockData.ts` stay only as type fixtures for unit tests if needed; runtime imports of `strategies`, `signals`, `marketTiles`, `marketNews`, `takenSignals`, `followedStrategyIds` are removed from app code.

## 5. Trader pages with no mocks

- Catalog → real Bayn-curated strategies will need a backend; until then it's an empty state with copy "Catalog coming soon" (keeps your "no mock" rule).
- Signals / Performance → empty states until real strategies are followed.
- Home sections honor the user's selected layout and asset classes, all populated from live Finnhub data or empty states.

## Technical notes

- Finnhub key requested via `add_secret` (`FINNHUB_API_KEY`).
- Asset class detection: stock if no suffix, crypto if `:`/`BINANCE:`, FX if 6-char `/`. Onboarding picker uses Finnhub `/search` filtered by enabled classes.
- All preference writes remain `bayn.prefs.[userId].[key]` so accounts stay isolated.
- Network: every Finnhub call goes through a server function; the publishable key is never shipped to the client.

## Files touched (high level)

- New: `src/lib/api/finnhub.functions.ts`, `src/lib/api/finnhub.server.ts`, `src/components/onboarding/*` (step components), `src/components/common/CustomizeButton.tsx`.
- Rewrite: `src/routes/onboarding.tsx`, `src/lib/api/trader.ts`, `src/lib/api/studio.ts`, `src/components/common/MarketTicker.tsx`, `src/routes/app.home.tsx`, `src/routes/studio.home.tsx`, all `studio.*` list pages.
- Edit: `src/components/layout/AppShell.tsx` (remove customize tab, ensure home Customize button).
- Cleanup: `src/lib/mockData.ts` no longer imported at runtime.

## Scope I'm explicitly NOT doing

- No broker integrations (TD/IBKR/etc.) — onboarding captures the preference and the live page shows "Coming soon".
- No real backtesting engine — Studio builder/backtests still placeholder until a backend exists.
- No email/SMS notification delivery — toggles persist; delivery is out of scope.