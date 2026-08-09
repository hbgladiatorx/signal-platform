# Signal Platform — Frontend Streamline Tasks (for Claude Code)

**Repo:** `signal-platform` · **Branch:** work off `main` (create a feature branch per task)
**Scope:** `frontend/` only. Do **not** touch backend `packages/` or `services/` unless a task explicitly says so.
**Stack (confirmed):** Next.js App Router, TypeScript, Tailwind, TanStack Query (`@tanstack/react-query`),
Auth0 (`@auth0/auth0-react`), lucide-react icons.

## How to use this file
Work **one task at a time, top to bottom.** For each task:
1. Read the referenced files first. Confirm the current state matches what's described (the repo evolves — if a
   path or detail differs, adapt to reality and note it).
2. Make the change in a dedicated branch: `git checkout -b ui/task-N-shortname`.
3. Keep the diff tight and scoped to the task. Run `npm run build` (and `npm run lint` if present) before finishing.
4. Commit with a clear message, then stop and let the human review before starting the next task.

**Global rules for every task**
- No new dependencies without calling it out and asking.
- Preserve existing auth, routing, and data-fetching patterns (`useApi`, TanStack Query).
- Do **not** invent backend endpoints. If a tile/feature needs data the API doesn't expose yet, render a clean
  "not available yet" state (see Task 3 for the pattern) — never a fake number and never the word "Phase".
- Keep it SSR-safe (the existing Sidebar shows the correct localStorage-in-useEffect pattern).
- Match existing code style (functional components, Tailwind classes, `cn()` helper).

---

## Task 1 — Grouped, complete sidebar navigation  ·  LOW effort / HUGE impact

**Problem:** `components/nav/Sidebar.tsx` lists only 7 items, but 20 routes exist. Backtests, Walk-forwards, and the
Sweep tool are **not reachable from the nav at all.** "Live & Paper" collapses two different modes into one link.

**File:** `frontend/components/nav/Sidebar.tsx`

**Do this:**
- Restructure `navItems` into three labeled groups. Render a small uppercase group heading above each group
  (muted, ~9px, letter-spacing). Keep the existing collapse behavior, active-route highlthe ighting via `usePathname()`,
  Keep the existing collapse behavior, active-route highlighting via `usePathname()`, icons from lucide-react, and
  localStorage persistence.
- Target structure:

  **RESEARCH**
  - Instruments → `/instruments` (icon: Database)
  - Signals → `/signals` (icon: Radio or Waves) *(route added in Task 7; until then, point to `/signals` — it's fine if it 404s until Task 7 lands, OR gate this item behind Task 7. Note which you chose.)*
  - Strategies → `/strategies` (icon: Workflow)
  - Backtests → `/backtests` (icon: BarChart3)
  - Walk-forwards → `/walkforwards` (icon: Activity or LineChart)
  - ML Models → `/ml` (icon: Brain)

  **TRADING**
  - Paper → `/paper` (icon: Radio)
  - Live → `/paper?mode=live` **only if** live has no dedicated route; otherwise its real route. Confirm from the
    `/paper` page how live vs paper is distinguished before wiring this. If they share one page, keep a single
    "Paper & Live" item rather than inventing a route.

  **SYSTEM**
  - Health → `/system/health` (icon: Activity)
  - Settings → `/settings` (icon: Settings)

- When the sidebar is **collapsed**, hide the group headings (show icons only), preserving current collapsed styling.

**Acceptance:**
- Every existing route is reachable from the nav (or intentionally nested — e.g. `/backtests/new` is reached from
  the Backtests list, not the nav).
- Active highlighting still works on nested routes (`/backtests/[id]` highlights Backtests).
- `npm run build` passes.

---

## Task 2 — Remove developer-roadmap language from all rendered UI  ·  LOW effort / HIGH impact

**Problem:** ~39 occurrences of "Phase N", "Step N", "coming soon", "TODO", "not yet" appear in **user-facing text**.
These belong in code comments, not on screen. They make a working product feel like a beta.

**Find them:**
```
grep -rniE "phase [0-9]|step [0-9]+|coming soon|not yet|TODO" frontend/app frontend/components
```

**Do this — for each USER-VISIBLE string (JSX text, labels, hints, empty states):**
- If the feature works: describe what it does, plainly.
- If the feature isn't wired yet: replace with a neutral status like **"Not enabled"** or **"No data yet"** — no
  roadmap phase numbers, no promises of future steps.
- Known hotspots to fix (confirm against current code):
  - `app/dashboard/page.tsx` — "Phase 1 in progress… Charts land in Step 11; strategies in Phase 2" and the
    `hint="Phase 2"` / `hint="Phase 4 (live)"` stat-card props. (Task 3 rebuilds this page — coordinate; if doing
    Task 3 next, you may delete rather than reword.)
  - `components/settings/DataSourcesSection.tsx` — "Phase 1 ships Binance.US. Phase 4 adds Alpaca…", "Coming soon".
  - `components/settings/ProfileSection.tsx` — "Reserved for Phase 4+ when alerts ship."
- **Leave code comments alone** — only change what renders to the screen.

**Acceptance:** the grep above returns **zero hits inside JSX/rendered strings** (comments may remain). `npm run build` passes.

---

## Task 3 — Rebuild the dashboard into a live "Command Center"  ·  MED effort / HUGE impact

**Problem:** `app/dashboard/page.tsx` is a stub: 3 stat cards (two hardcoded to `0` with "Phase 2/4" hints) plus a
"Phase 1 in progress" paragraph. It's the first authenticated screen and reads as unfinished.

**File:** `frontend/app/dashboard/page.tsx` (+ small components as needed under `components/`)

**Do this:**
- Rename the page heading to **"Command Center"** (keep the route `/dashboard`).
- Build a tile grid that reflects **real state pulled from the existing API**. Before writing tiles, check
  `lib/api.ts` / `lib/useApi.ts` and the API for which of these are actually available, and only render tiles whose
  data exists:
  - **Data feed** — live/streaming status + instrument count (already have `/instruments`).
  - **Last backtest** — most recent backtest's return/Sharpe (check for a backtests list endpoint).
  - **Best walk-forward** — top out-of-sample Sharpe (check walkforwards endpoint).
  - **Paper P&L** — current paper session P&L if a paper endpoint exists.
- **Empty/absent-data pattern (reuse everywhere):** if an endpoint isn't available, render the tile in a muted
  "Not available yet" state with a short explanation — **never** a hardcoded `0` and never "Phase N".
- Add **one primary call-to-action** button, prominent, top-right of the header area: **"+ New Backtest"** →
  routes to `/backtests/new`. This is the single obvious next action.
- Optional: a one-line "Continue where you left off" hint linking to the most recent in-progress item, if such data
  is cheaply available. Skip if it requires new backend work.

**Acceptance:**
- No hardcoded zeros, no "Phase" text.
- Every tile either shows real API data or a clean not-available state.
- The "+ New Backtest" CTA is visible and works.
- `npm run build` passes.

---

## Task 4 — One primary action + "next step" per page (the funnel)  ·  MED effort / HIGH impact

**Problem:** the core loop — **instrument → signals → strategy → backtest → edge check → walk-forward → paper →
live** — is invisible. Each page is an island, so users don't know what to do next.

**Files:** the list/detail pages under `app/strategies`, `app/backtests`, `app/walkforwards`, `app/paper`
(and their `[id]` detail pages).

**Do this:**
- On each **detail/results page**, add a single prominent primary button that advances the funnel:
  - Strategy detail → **"Backtest this strategy"** → `/backtests/new?strategy=<id>` (use existing param conventions;
    confirm how `new` reads presets).
  - Backtest results (`/backtests/[id]`) → **"Run walk-forward"** → `/walkforwards/new?backtest=<id>`.
  - Walk-forward results (`/walkforwards/[id]`) → **"Deploy to paper"** → `/paper/new?strategy=<id>`.
  - Paper session (`/paper/[id]`) → **"Promote to live"** — but **gated**: this must require explicit confirmation
    and only appear when the platform permits live (mirror the backend's existing live-gating; do not bypass it).
- Keep secondary actions secondary (quieter styling). Exactly **one** visually-dominant primary action per page.
- Where a page is a list, the primary action is the "create" action (e.g. "New backtest") and it doubles as the
  empty-state CTA (see Task 5).

**Acceptance:** each results page has exactly one dominant next-step button that deep-links correctly with the right
preset params. The live promotion path remains gated/confirmed. `npm run build` passes.

---

## Task 5 — Breadcrumbs + consistent empty states  ·  LOW effort / MED impact

**Problem:** `components/nav/AppShell.tsx` takes a `title` but there's no breadcrumb, so users lose context on deep
pages like `/backtests/[id]`. Empty lists likely render blank.

**Do this:**
- **Breadcrumbs:** add a breadcrumb row in `components/nav/Header.tsx` (or AppShell) driven by the route segments,
  e.g. `Research / Backtests / #1234`. Keep it subtle. Map the top segment to its nav group from Task 1.
- **Empty states:** create one reusable `EmptyState` component (`components/ui/EmptyState.tsx`) with an icon, a
  one-line message, and an optional primary action. Use it on every list page (`/backtests`, `/strategies`,
  `/walkforwards`, `/paper`) when the list is empty — e.g. *"No backtests yet — run your first."* with the CTA.
- **Loading states:** ensure lists show a skeleton/loading indicator (TanStack Query `isLoading`) rather than a
  blank flash.

**Acceptance:** deep pages show a breadcrumb; every list page has a friendly empty state with a next action; no blank
white flashes on load. `npm run build` passes.

---

## Task 6 — Reserve status colors for status only  ·  LOW effort / MED impact

**Problem:** ~20 color tokens are in use; red appears 100+ times, mixing brand/decoration with error semantics, so
"is this bad, or just styled?" is ambiguous.

**Do this:**
- Audit color usage:
  `grep -rhoE "(navy|gold|gray|blue|green|red|slate|zinc)-[0-9]{3}" frontend/app frontend/components | sort | uniq -c | sort -rn`
- Establish and document (a short comment in `tailwind.config.ts` or a `frontend/README` note) this convention:
  - **green** = gain / healthy / pass, **red** = loss / error / fail, **amber/yellow** = warning — **status only.**
  - **navy + one accent** (pick the existing blue or gold) for all non-status UI (buttons, links, highlights).
- Replace decorative reds/greens (used purely for styling, not meaning) with the navy/accent or neutral grays.
- Consolidate near-duplicate grays where trivial (don't over-engineer; focus on the status/decoration split).
- Every status color should pair with text or an icon, not stand alone (accessibility).

**Acceptance:** red/green/amber appear only where they convey gain/loss/warning/health; buttons and decoration use
navy/accent. `npm run build` passes.

---

## Task 7 — Add the Signals page + inline edge-gate on backtest results  ·  MED effort / MED impact

**Context:** two research tools exist as a separate Python package (`sentinel`): a dark-pool/options-flow
**intelligence dashboard** and a **predictive-edge study** (Information Coefficient / bootstrap p-value / verdict).
This task surfaces them in the UI. **Backend endpoints may not exist yet** — if so, build the UI against a typed
API contract and wire a clear "connect data source" placeholder, and note exactly which endpoints are needed.

**Do this:**
- **New route `app/signals/page.tsx`:** a "Signals" page under the Research nav group (matches Task 1). It shows
  per-ticker institutional-activity intel (dark-pool notional, options-flow notional, call/put split, an
  **activity score**, and a **direction marked UNCERTAIN with confidence capped ≤ 0.5**). Preserve the honesty
  framing: this is *situational awareness, not buy/sell signals* — include the caveat banner (prints show size not
  side; large prints are often hedges; data is delayed).
- **Inline edge-gate on `app/backtests/[id]/page.tsx`:** add a compact "Predictive-edge check" card showing the
  study verdict for the strategy's signal — one of **NO EDGE / MARGINAL / SHOWS EDGE** with IC and p-value — styled
  as a **gate**: if verdict is NO EDGE, the "Deploy to paper/live" actions from Task 4 should be visually
  discouraged (disabled with a tooltip "No measured edge — validate before deploying"). Never hard-block research,
  but make the recommendation loud.
- If the backend doesn't expose these yet, render the components with a typed loading/empty state and **document the
  required endpoints** at the top of each new file as a comment (e.g. `GET /signals/intel`, `GET /backtests/:id/edge`).

**Acceptance:** `/signals` renders and is linked in the nav; backtest results page shows the edge-verdict gate;
honesty caveats are present; required-but-missing endpoints are clearly documented, not faked. `npm run build` passes.

---

## Suggested commit sequence
1 → 2 → 3 → 4 → 5 → 6 → 7. Ship and review each before the next. Tasks 1–2 alone remove most of the "unclear" feeling.
```
```
