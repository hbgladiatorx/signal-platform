# Trader Personalization Pass

This is a large, trader-side-only rewrite. Studio stays untouched. Below is the build order so nothing breaks mid-way.

## 0. Onboarding-once fix (first, small)
Today `AuthGate` calls `resetAllPrefs()` every time it sees `!onboarded`, which can wipe progress mid-flow. Change:
- `setOnboarded(true)` as soon as the user enters step 1 of `/onboarding` (or move it to the start). The "finished" state we actually care about is now `traderSeeded` / `studioSeeded`.
- `AuthGate`: redirect to `/onboarding` only if `!onboarded`. Never `resetAllPrefs()` from the gate.
- Sign-out is the only place that calls `resetAllPrefs()`.

## 1. Single preferences store
New `src/lib/userPreferences.ts` — typed store + React hook + imperative read/write, localStorage-backed (Supabase-ready shape):

```
{
  enabledAssetClasses, watchedTickers[], newsSources[], newsTopics[],
  followedStrategies[], liveTrackingStrategyId, homeLayout[],
  hiddenSections[], defaultTimeframe, defaultChartType,
  accountSize, riskPerTrade, onlyNewsForWatched, notifications{}
}
```

Replaces the scattered helpers in `user-prefs.tsx` for trader surfaces. Old `user-prefs.tsx` is kept as a thin shim that delegates so existing imports keep working during migration.

## 2. Strip the mock defaults (trader side only)
In `src/lib/mockData.ts`:
- `marketTiles`, `marketNews`, `followedStrategyIds`, `takenSignals`, default open signals — keep arrays defined (catalog/storefront still needs `strategies` and the firing `signals` pool) but no longer auto-seed any trader surface.
- API layer (`src/lib/api/trader.ts`, `news.ts`) reads from preferences only. No fallbacks to mock arrays.

Catalog keeps showing all 16 strategies — it's the storefront.

## 3. Reusable components
- `EmptyState` (icon, headline, body, CTA)
- `TickerPicker` modal (search by symbol, asset class detect)
- `StrategyPicker` modal (filter by followed/all)
- `PaywallModal` (3 paths: upgrade / add slot / swap)
- `SlotBadge`, `LockedTabOverlay`, `HomeLayoutEditor`, `CustomizeShell`

## 4. `/app/customize` hub
New route with tabs: Markets & Tickers · News · Strategies · Home Layout · Trading Defaults · Notifications. Tab routed via `?tab=...`. Added to sidebar between Settings and Agent.

## 5. Inline controls
- Market overview bar: trailing `+` button, per-tile context menu (remove/move)
- Live Tracking card header: strategy dropdown + unpin
- My Strategies header: "Manage" → `/app/customize?tab=strategies`
- Market Wire: "Filter sources" chip → inline popover
- Home header: pencil → side sheet with `HomeLayoutEditor`

## 6. Strategy paywall & slot system
`src/lib/api/billing.ts` gains:
- `checkSlotAvailability(strategyId)` → `{ ok, reason, freeSlots, paidSlots, addOnSlots }`
- `consumeSlot(strategyId)`, `releaseSlot(strategyId)`
- `purchaseAddOn('extra-slot' | 'slot-bundle-5')`
- `upgradePlan(tier)`

Catalog + strategy detail follow buttons read state and switch label: **Follow / Upgrade to follow / Add slot to follow**. Free strategies (one per asset class) are exempt.

Locked strategy detail: signal feed + recent signals tabs blurred with `LockedTabOverlay`; backtest / OOS / forward stay open.

## 7. Surface migration
Touch every trader page so it reads `userPreferences` + falls back to `EmptyState`:
- `/app/home` (every zone) · `/app/catalog` (storefront, no change to data, but filter chips respect `enabledAssetClasses`) · `/app/signal/$id` · `/app/strategy/$id` · `/app/performance` · `/app/agent`
- `MarketTicker`, `NewsTicker`, market overview, live tracking — all driven by preferences.

## 8. Asset-class master toggle cascade
A single source — `enabledAssetClasses` — gates: asset filter chips, ticker tape, catalog chips, signal feed asset filter, performance breakdown. Tickers of disabled classes are hidden but kept in prefs (banner: "X tickers hidden — re-enable to see them").

## Files

**New**
- `src/lib/userPreferences.ts`
- `src/lib/api/news.ts`
- `src/components/common/EmptyState.tsx`
- `src/components/common/TickerPicker.tsx`
- `src/components/common/StrategyPicker.tsx`
- `src/components/common/SlotBadge.tsx`
- `src/components/common/LockedTabOverlay.tsx`
- `src/components/billing/PaywallModal.tsx`
- `src/components/customize/HomeLayoutEditor.tsx`
- `src/components/customize/CustomizeShell.tsx`
- `src/routes/app.customize.tsx`

**Edited**
- `src/components/AuthGate.tsx` (no more reset)
- `src/routes/onboarding.tsx` (mark onboarded early)
- `src/lib/user-prefs.tsx` (delegate to new store)
- `src/lib/mockData.ts` (drop trader-side defaults)
- `src/lib/api/trader.ts` + `src/lib/api/billing.ts`
- `src/lib/api.ts` (re-exports)
- `src/components/layout/AppShell.tsx` (sidebar entry, asset-class cascade)
- `src/components/common/MarketTicker.tsx`, `NewsTicker.tsx`
- `src/routes/app.home.tsx`, `app.catalog.tsx`, `app.signals.tsx`, `app.signal.$id.tsx`, `app.strategy.$id.tsx`, `app.performance.tsx`

## Scope confirmation
Studio (`/studio/*`) is untouched. The four free verified strategies per asset class remain free-forever and bypass paywall checks.

This is a one-shot rewrite — no half-state. Reply **approve** to proceed and I'll ship it all in one pass.