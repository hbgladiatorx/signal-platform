# Step 29 — Frontend NL → Python → Save UX

Adds an in-browser strategy authoring page that lets users describe a strategy
in plain English, see the generated Python, edit it, and save it.

## What This Ships

| File | Status | Purpose |
|------|--------|---------|
| `frontend/app/strategies/new/page.tsx` | NEW | The NL input → code review → save flow |
| `frontend/app/strategies/page.tsx` | REPLACES Step 24 version | Adds "+ New strategy" button; shows source badge (built-in vs yours) on each card |

No backend changes. No new dependencies. No migration. Just frontend.

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step29-nl-frontend.zip
git status
git add -A
git commit -m "Step 29: frontend NL → Python → save UX for user strategies"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build frontend
docker compose up -d --force-recreate frontend
# Frontend build takes ~60-90s (Next.js bundling)
```

Once it's up, the new pages will be live.

## Verify in Browser

1. **`https://signal.cimcha.com/strategies`** — should now show two buttons at top right:
   - "+ New strategy" (outlined, navy)
   - "New backtest" (filled, navy)
   - Each strategy card has a badge: "built-in" (gray) or "yours" (blue)

2. **Click "+ New strategy"** → goes to `/strategies/new` with:
   - Card 1: Big NL textarea + "Generate Python" button
   - (Cards 2 and 3 hidden until you generate)

3. **Type a description** like:
   > Buy BTC when 14-period RSI drops below 30, sell when above 70. Small position size.
   
   Click **Generate Python**. ~12 seconds, then:
   - Card 2 appears with explanation banner (blue) and editable code area
   - Card 3 appears with name pre-filled (e.g., "RsiMeanReversion") and a Save button

4. **Click "Save strategy"** — redirects to `/strategies`, new card appears with "yours" badge.

5. **Test the round-trip**: from the new strategy card, click "Backtest this →", configure, submit. Should run and complete just like a built-in.

## Known Limitations (Future Polish)

- Plain `<textarea>` instead of Monaco — no syntax highlighting or line numbers. (Monaco integration is ~2MB lazy-loaded chunk; left for a polish step.)
- No client-side re-validation as the user edits. Server validates on save.
- No multi-turn refinement UI ("make the entry stricter"). The translate endpoint supports it (`previous_source` + `feedback`) but the frontend doesn't expose it yet.
- No cost display on the page (just in token counts after generation). A cumulative cost tracker is future work.
- Single-shot only — clicking "Regenerate" loses the edited code without warning. Consider a confirmation modal.

## What This Completes

Phase 2 Milestone C goal: in-browser strategy authoring works end-to-end.

A user can now:
1. Sign in
2. Describe a strategy in English
3. Watch Claude generate Python
4. Review, edit if needed
5. Save it
6. Run a backtest against it
7. View results — same UX as a built-in strategy

All without ever opening a terminal.
