# Walk-Forward Stage 2 — Frontend

Adds three pages and one types file for the walk-forward feature.

## Files

```
frontend/lib/walkforward-types.ts          (types + formatters + overfit badge)
frontend/app/walkforwards/page.tsx         (list view)
frontend/app/walkforwards/new/page.tsx     (create form)
frontend/app/walkforwards/[id]/page.tsx    (detail view with cards + table)
```

## Install steps (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step33-walkforward-frontend.zip
ls frontend/app/walkforwards/
# Should list: page.tsx, new/, [id]/
```

## Auth import — verify this works

These pages import `fetchAuthed` and `API_BASE` from `@/lib/api`:

```ts
import { fetchAuthed, API_BASE } from "@/lib/api";
```

If your project uses a different module path or export name (e.g.
`@/lib/apiClient`, `fetchWithAuth`, etc.) — adjust the three pages. Your
existing `backtests/page.tsx` already imports an auth-fetch helper; copy
that exact import statement.

To check what your existing pages use:

```bash
head -30 frontend/app/backtests/page.tsx
```

Replace `fetchAuthed`/`API_BASE` in the three new pages with whatever your
existing pattern is.

## Sidebar nav link

Find the file that renders your sidebar (likely
`frontend/components/Sidebar.tsx` or `frontend/app/layout.tsx`) and add a
Walk-Forwards link next to your Backtests / Sweep links. Example:

```tsx
<NavLink href="/walkforwards" label="Walk-Forwards" />
```

If you don't have a nav component, the routes are still reachable at
`/walkforwards`, `/walkforwards/new`, and `/walkforwards/{id}`. You can
also link from the Backtests page:

```tsx
<Link href="/walkforwards" className="...">Walk-Forwards</Link>
```

## API endpoints expected (already shipped in Stage 1)

| Method | Path                       | Purpose                  |
|--------|----------------------------|--------------------------|
| GET    | `/walkforwards`            | List walkforwards        |
| GET    | `/walkforwards/{id}`       | Get one (with windows)   |
| POST   | `/walkforwards`            | Create + enqueue         |

Pages assume these return JSON shaped like the Pydantic models in
`services/api/routers/walkforwards.py` (and matching the TS types in
`frontend/lib/walkforward-types.ts`).

## Ship

```bash
cd ~/signal-platform
git add -A
git commit -m "Walk-forward Stage 2: list / new / detail pages"
git push
```

## Deploy on box

```bash
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
```

Open `https://signal.cimcha.com/walkforwards` in your browser — should
show the table with your existing walkforward row (the one we tested at
ID `8380f4c9-c6b2-49f4-88e7-5247871fdee7`).

Click the row → detail page shows the four summary cards, per-window
cards (5 of them), and per-window table at the bottom.

## What success looks like

- **List page**: row for the SMACrossover walkforward, columns populated:
  Train Sharpe 1.54, Test Sharpe −1.85, Overfit badge "Severe",
  Win Rate 0%, Runtime 2.9s
- **Detail page**: four summary cards visible at top, five per-window
  cards in a grid, dense table below them with all metrics populated

## Known limitations of this milestone

- Only single-symbol walkforwards are supported in the UI. The engine
  already supports multi-symbol; we'll wire that next milestone.
- No equity curve plot per window yet. The dataclass doesn't currently
  surface per-bar equity for individual windows (only summary stats).
  Adding that is a backend-side change; tracked in the backlog.
- Param grid editor is basic key/value text. The full Sweep-style
  multi-row editor is sufficient but lacks per-param type hints.

## Risk note

Walk-forward analysis is a diagnostic for overfit risk, not a forecast of
live performance. Out-of-sample windows are still historical. Trading
involves substantial risk; you may lose your entire investment.
Educational use only — not investment advice.
