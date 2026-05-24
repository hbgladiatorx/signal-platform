# Backtests list — Period column

Adds a "Period" column to the backtests list page showing the testing window in compact form (e.g. `2.6d`, `1.4y`), color-coded by sample size.

## Files Included

| File | Change |
|------|--------|
| `services/api/routers/backtests.py` | Added `bars_start`, `bars_end`, `num_bars` to `BacktestSummary` Pydantic model + list endpoint |
| `frontend/app/backtests/page.tsx` | Added "Period" column with color-coded compact format + tooltip |

## Files To Patch In Place

| File | Why a script not a replacement |
|------|--------------------------------|
| `frontend/lib/backtest-types.ts` | I only saw the relevant chunk, not the whole file — a surgical patch is safer than guessing at the rest |

## Apply (Mac)

```bash
cd ~/signal-platform

# 1. Drop in the replacement files
unzip -o ~/Downloads/step30-list-period.zip

# 2. Surgical patch to backtest-types.ts: add 3 fields to BacktestSummary
python3 <<'PY'
import pathlib
p = pathlib.Path("frontend/lib/backtest-types.ts")
text = p.read_text()

# Find the BacktestSummary interface and add 3 fields right before its closing brace.
# Anchor on `win_rate_pct?: number | null;\n}` which is the last field + close.
old = '  win_rate_pct?: number | null;\n}'

new = """  win_rate_pct?: number | null;
  // Sample size info — added for the Period column in the list
  bars_start?: string | null;
  bars_end?: string | null;
  num_bars?: number | null;
}"""

if 'bars_start' in text and 'BacktestSummary' in text.split('bars_start', 1)[0]:
    # Already patched (heuristic: bars_start appears in the file and before our target)
    print("Already patched.")
elif old in text:
    # Patch only the FIRST occurrence (BacktestSummary), not BacktestDetail's
    # (BacktestDetail already has bars_start etc.)
    text = text.replace(old, new, 1)
    p.write_text(text)
    print("Patched: added bars_start/bars_end/num_bars to BacktestSummary.")
else:
    print("ERROR: didn't find expected anchor in backtest-types.ts.")
    print("Manually add these 3 fields to the BacktestSummary interface:")
    print("  bars_start?: string | null;")
    print("  bars_end?: string | null;")
    print("  num_bars?: number | null;")
    raise SystemExit(1)
PY

# 3. Verify
grep -A 30 "interface BacktestSummary" frontend/lib/backtest-types.ts | head -35

# 4. Commit + push
git add -A
git diff --stat --cached
git commit -m "Backtests list: Period column showing days tested, color-coded by sample size"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build api frontend
docker compose up -d --force-recreate api frontend
sleep 15
```

The api rebuild picks up the new `BacktestSummary` fields; the frontend rebuild picks up the new column.

## Verify

1. Go to `/backtests`. You should see a new **PERIOD** column between RES. and STATUS.

2. Existing rows should show their testing window in compact form:
   - **Red** for under 7 days (severely insufficient)
   - **Amber** for 7–30 days (short)
   - **Gray** for 30–90 days (limited)
   - **Green** for 90+ days (reasonable)
   - **—** if `bars_start`/`bars_end` aren't populated

3. Hover any value → tooltip with a sentence explaining the tier.

## If All Rows Show "—"

That means the list endpoint isn't returning `bars_start`/`bars_end` even though the column has been added. Most likely cause: `list_backtests_for_user` in `packages/backtest/persistence.py` has a SELECT statement that only includes specific columns, and the new ones aren't in the list.

To diagnose, paste me:

```bash
grep -A 30 "def list_backtests_for_user" packages/backtest/persistence.py
```

Then I'll write a one-line patch to add the columns to the SELECT.

## Backward Compatibility

- `BacktestSummary` Pydantic adds optional fields with defaults → existing clients unaffected
- TypeScript adds optional fields → existing components unaffected
- The list page additions are non-breaking; older detail/new-backtest pages don't care
