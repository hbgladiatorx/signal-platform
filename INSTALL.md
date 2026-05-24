# Step 29 Polish — Clickable backtest rows + collapsible sidebar

Two UI improvements, frontend-only, no backend changes.

## Files

| File | Status | Purpose |
|------|--------|---------|
| `frontend/app/backtests/page.tsx` | REPLACED | Each row is now clickable → goes to the detail page |
| `frontend/components/nav/Sidebar.tsx` | REPLACED | Toggle button to collapse the sidebar to icon-only mode |

## What's New

### Backtests list — clickable rows
- Entire row is now clickable (`role="button"`, keyboard accessible via Enter/Space)
- Hover state: subtle navy tint
- Strategy name keeps its existing link with `stopPropagation` so middle-click still opens in a new tab cleanly
- Helper text updated to mention click-to-detail

### Sidebar — collapse to icon rail
- Chevron toggle button in the top-right corner of the sidebar header
- Collapsed width: 64px (just enough for the icons)
- Expanded width: 240px (unchanged)
- Smooth 200ms width transition
- Tooltip on each nav icon when collapsed (`title` attribute)
- State persists across page loads via `localStorage` (key: `sidebar-collapsed`)
- SSR-safe: hydrates with expanded default, then updates from localStorage on mount

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step29-polish.zip
git status
git add -A
git commit -m "Step 29 polish: clickable backtest rows + collapsible sidebar"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
# ~60-90s for Next.js bundling
```

## Verify

1. Go to `/backtests`. Hover a row — should turn light navy. Click anywhere on the row (not the strategy name) — should navigate to the detail page.

2. Look at the sidebar — there's a small chevron-left icon at the top right. Click it. The sidebar should smoothly shrink to a column of icons. Click again — expands back.

3. Reload the page while collapsed. The sidebar should stay collapsed (localStorage persistence).

4. Open in a new tab — also opens collapsed.

## Known Limitations

- Tooltip is just the native browser `title` attribute (delay before showing, basic styling). Could upgrade to a proper Tooltip component later if it bothers you.
- localStorage only — no cross-tab sync. If you have two tabs open and collapse in one, the other won't update until reload.
