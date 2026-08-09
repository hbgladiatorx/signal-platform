# Signal Platform — Frontend Tasks v2 (CORRECTED for the rebuilt app)

> **⚠️ This REPLACES the earlier `FRONTEND_CLEANUP_TASKS.md`.** The frontend was rebuilt. The old file targeted a
> Next.js app under `frontend/` that no longer exists. Delete/ignore the old one.

**App location:** `apps/studio/`
**Stack (confirmed from source):** TanStack Start, React 19, Vite, **Bun** (not npm), shadcn/ui, Supabase, and a typed
FastAPI client (`src/lib/api/client.ts`). Routes live in `apps/studio/src/routes/` (TanStack file-based routing).
**Two modes:** Trader (`/app/*`) and Studio (`/studio/*`), switched via `AppShell` `mode` prop.

## How to use this file
One task at a time. For each: read the referenced files, make a branch (`git checkout -b ui/v2-taskN`), keep the diff
tight, then **build with Bun**:
```
cd apps/studio && bun install && bun run build
```
(Confirm the exact script names in `apps/studio/package.json` — use `bun run <script>`, not npm.)
Commit, stop, let the human review before the next task.

**Global rules**
- No new dependencies without asking.
- Preserve the TanStack Query + typed-client (`lib/api/*`) and Supabase patterns already in use.
- Do **not** invent backend endpoints or fabricate data. If real data isn't available, render a clean empty/"not
  available" state — never a hardcoded number.
- Match the existing shadcn/ui + Tailwind + `cn()` conventions.

---

## Task 1 — Kill the last mock data  ·  LOW effort / HUGE impact
**Problem:** `src/lib/mockData.ts` is a seeded PRNG producing fake strategies with fabricated Sharpe/win-rate/subscriber
numbers. It is imported by **exactly one** route: `src/routes/app.customize.tsx`. Everything else uses real data, so this
one page shows convincing fake performance — the most dangerous inconsistency.

**Do this:**
- Open `src/routes/app.customize.tsx`. Replace its `import { strategies } from "@/lib/mockData"` usage with the real
  data source (check `src/lib/api/trader.ts` / `studio.ts` for the appropriate call, e.g. catalog/strategies), wired via
  TanStack Query like the other routes.
- If no real endpoint fits what this page needs, render a proper empty state (with a CTA) instead of fake rows — do not
  keep fabricated numbers.
- **Delete `src/lib/mockData.ts`** once nothing imports it. Verify: `grep -rn "mockData" src` returns nothing.

**Acceptance:** `grep -rn "mockData" src` is empty; `app.customize` shows real data or a clean empty state;
`bun run build` passes.

---

## Task 2 — Remove the duplicate ticker tape  ·  TRIVIAL / MED impact
**Problem:** `src/components/layout/AppShell.tsx` renders `<TVTickerTape />` **twice** in trader mode (around lines 170
and 175) — one above and one below the `<AssetChipRow />`. Two scrolling tickers appear.

**Do this:** keep a single `<TVTickerTape />` (the one directly under the header, above the asset chips) and delete the
duplicate render. Confirm only one `<TVTickerTape />` remains in the trader branch.

**Acceptance:** `grep -n "TVTickerTape" src/components/layout/AppShell.tsx` shows the import + exactly one render;
`bun run build` passes.

---

## Task 3 — Real notification badge + real username  ·  LOW effort / MED impact
**Problem:** in `AppShell.tsx` the notification bell shows a hardcoded `3` badge, and the account dropdown shows a literal
`@trader` instead of the signed-in user.

**Do this:**
- Username: pull the real user from the Supabase session (`src/integrations/supabase/client.ts` is already used for
  sign-out). Show the real handle/email; fall back gracefully if absent.
- Notification badge: if a notifications source exists, wire the count and **hide the badge when zero**. If notifications
  aren't built yet, remove the hardcoded badge rather than showing a fake "3".

**Acceptance:** no hardcoded `3` or `@trader` in `AppShell.tsx`; badge reflects real state or is absent; build passes.

---

## Task 4 — Make the header search real, or remove it  ·  LOW–MED / MED impact
**Problem:** the header `<Input placeholder="Search strategies, symbols…">` in `AppShell.tsx` has no handler — it's a
dead control.

**Do this:** either wire it to a real search (route or API), or remove it until search exists. Do not ship a prominent
control that does nothing. If you build it, debounce and route results sensibly per mode (strategies/symbols in trader,
strategies/nodes in studio — the placeholder already distinguishes them).

**Acceptance:** the search either works or is gone; build passes.

---

## Task 5 — Surface "validated out-of-sample" on strategy/catalog cards  ·  MED / HIGH impact
**Problem:** cards show Sharpe, win-rate, and subscriber counts, but **not** whether the strategy's edge survived
out-of-sample / walk-forward — which is this platform's actual differentiator and the only number that means much.

**Do this:**
- Check `src/lib/api/studio.ts` / `walkforward.ts` and the strategy types for an out-of-sample / walk-forward result
  field (e.g. forward win-rate, an OOS Sharpe, or a validation flag). The types already reference
  `forward_win_rate` and `annualized_return_pct` — use the real field.
- Add a compact badge/verdict to the strategy and catalog cards (`src/components/common/*` and the catalog/strategy
  routes): e.g. **Validated OOS ✓ / Marginal / Not validated**. De-emphasize vanity metrics (subscriber counts)
  relative to this.
- If the field isn't available for an item, show "Not validated" — never imply validation that didn't happen.

**Acceptance:** strategy + catalog cards show an honest OOS/validation state driven by real data; build passes.

---

## Task 6 — aria-labels on icon-only buttons  ·  LOW / LOW impact
**Problem:** ~17 icon-only buttons, ~11 aria-labels. Icon buttons without labels fail screen-reader a11y.

**Do this:** add `aria-label` to every icon-only `<Button size="icon">` (bell, avatar, sidebar collapse, etc.).
Optionally enable the relevant `eslint-plugin-jsx-a11y` rule in `eslint.config.js` to prevent regressions.

**Acceptance:** every icon-only button has an `aria-label`; build + lint pass.

---

## Task 7 — Shared QueryState (loading / empty / error) across the 23 data routes  ·  MED / MED impact
**Problem:** 23 routes use TanStack Query; handling of loading/empty/error is likely inconsistent (some skeletons, some
blank flashes, some silent errors).

**Do this:** create `src/components/common/QueryState.tsx` — a wrapper taking a query result and rendering: a skeleton
while loading, a friendly empty state (with optional CTA) when data is empty, and an error state with a retry button.
Adopt it incrementally across list + detail routes (start with home, catalog, signals, backtests, walkforward).

**Acceptance:** a reusable QueryState exists and is used on the primary routes; no blank flashes; errors are visible with
retry; build passes.

---

## Suggested order
1 → 2 → 3 → 4 → 5 → 6 → 7. Task 1 (kill mock data) is the single highest-value change. Tasks 2–4 are quick header
credibility fixes. Task 5 is the one that makes the product's honesty visible.
