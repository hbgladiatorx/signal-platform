# Step 33 Stage 1 — Walk-Forward Backend

Backend-only. No UI yet. Tested via `curl`. Frontend ships in Stage 2.

## What This Ships

**New files:**
- `migrations/versions/0007_walkforwards.sql` — new `walkforwards` table
- `packages/backtest/walkforward.py` — orchestration logic
- `packages/backtest/walkforward_persistence.py` — CRUD helpers
- `services/api/routers/walkforwards.py` — POST/GET endpoints

**Patches needed (heredoc instructions below):**
- `packages/data/messagebus.py` — add `QUEUE_WALKFORWARD_JOBS` constant
- `services/api/main.py` — register the new router
- `services/backtest_worker/main.py` — handle walkforward queue jobs

## Apply

### 1. Unzip and verify new files landed

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step33-walkforward-backend.zip
ls migrations/versions/0007_walkforwards.sql
ls packages/backtest/walkforward.py
ls packages/backtest/walkforward_persistence.py
ls services/api/routers/walkforwards.py
```

All four should exist.

### 2. Apply the three patches

```bash
cd ~/signal-platform

python3 <<'PY'
import pathlib

# --- Patch 1: messagebus constant ---
p = pathlib.Path("packages/data/messagebus.py")
src = p.read_text()
if "QUEUE_WALKFORWARD_JOBS" in src:
    print("messagebus: already patched")
else:
    # Find QUEUE_BACKTEST_JOBS line and add walkforward next to it
    anchor = 'QUEUE_BACKTEST_JOBS'
    if anchor not in src:
        print("messagebus: ERROR anchor not found")
    else:
        idx = src.find(anchor)
        line_end = src.find("\n", idx)
        line = src[idx:line_end]
        # Replicate the same style for the new constant
        new_line = line.replace("BACKTEST_JOBS", "WALKFORWARD_JOBS").replace("backtest:jobs", "walkforward:jobs")
        src = src[:line_end + 1] + new_line + "\n" + src[line_end + 1:]
        p.write_text(src)
        print("messagebus: patched")
        print("  added:", new_line)

# --- Patch 2: register router in API main ---
p = pathlib.Path("services/api/main.py")
src = p.read_text()
if 'from services.api.routers.walkforwards' in src or '"walkforwards"' in src:
    print("api main: already patched")
else:
    # Add import next to other router imports
    import_anchor = 'from services.api.routers.backtests'
    if import_anchor not in src:
        print("api main: ERROR import anchor not found")
    else:
        # Find the line, append new import after it
        idx = src.find(import_anchor)
        line_end = src.find("\n", idx)
        existing_line = src[idx:line_end]
        # Mirror the import style
        new_import = existing_line.replace("backtests", "walkforwards")
        src = src[:line_end + 1] + new_import + "\n" + src[line_end + 1:]

        # Add app.include_router call. Look for the backtests router include line.
        include_anchor_lines = [
            'app.include_router(backtests.router',
            'app.include_router(backtests_router',
            'include_router(backtests',
        ]
        included = False
        for a in include_anchor_lines:
            if a in src:
                idx = src.find(a)
                line_end = src.find("\n", idx)
                existing_line = src[idx:line_end]
                new_include = existing_line.replace("backtests", "walkforwards")
                src = src[:line_end + 1] + new_include + "\n" + src[line_end + 1:]
                included = True
                break
        if not included:
            print("api main: WARN could not find router include anchor — patch manually:")
            print("  app.include_router(walkforwards.router)")
        p.write_text(src)
        print("api main: patched")

# --- Patch 3: worker handles walkforward queue ---
p = pathlib.Path("services/backtest_worker/main.py")
src = p.read_text()
if "QUEUE_WALKFORWARD_JOBS" in src:
    print("worker: already patched")
else:
    # 3a. Update messagebus import
    old = "from packages.data.messagebus import QUEUE_BACKTEST_JOBS"
    new = "from packages.data.messagebus import QUEUE_BACKTEST_JOBS, QUEUE_WALKFORWARD_JOBS"
    if old in src:
        src = src.replace(old, new)
    else:
        print("worker: WARN import line not found, add manually:", new)

    # 3b. Add walkforward processing imports near the persistence imports
    old = "from packages.backtest.persistence import ("
    insert_block = (
        "from packages.backtest.walkforward import run_walkforward\n"
        "from packages.backtest.walkforward_persistence import (\n"
        "    load_walkforward,\n"
        "    mark_walkforward_failed,\n"
        "    mark_walkforward_running,\n"
        "    save_walkforward_results,\n"
        ")\n"
    )
    if old in src and "from packages.backtest.walkforward import" not in src:
        src = src.replace(old, insert_block + old)

    # 3c. Update BRPOP to listen to both queues
    old_brpop = "[QUEUE_BACKTEST_JOBS]"
    new_brpop = "[QUEUE_WALKFORWARD_JOBS, QUEUE_BACKTEST_JOBS]"
    if old_brpop in src:
        src = src.replace(old_brpop, new_brpop)
    else:
        print("worker: WARN BRPOP list anchor not found")

    # 3d. Dispatch on queue name. Find where we currently call _process_job(backtest_id, ...)
    old_dispatch = "await _process_job(backtest_id, engine, strategies_cache)"
    new_dispatch = """if _queue_name == QUEUE_WALKFORWARD_JOBS:
                await _process_walkforward_job(backtest_id, engine, strategies_cache)
            else:
                await _process_job(backtest_id, engine, strategies_cache)"""
    if old_dispatch in src:
        src = src.replace(old_dispatch, new_dispatch)
    else:
        print("worker: WARN dispatch anchor not found")

    # 3e. Append the _process_walkforward_job function right after _process_job.
    # Find the end of _process_job by looking for the next async def / # ====... block.
    handler_code = '''


# ============================================================
# Walkforward job processing
# ============================================================
async def _process_walkforward_job(
    walkforward_id: UUID,
    engine: AsyncEngine,
    strategies_cache: dict[str, Type[Strategy]],
) -> None:
    """Process one walk-forward job end-to-end."""
    log.info("backtest_worker.walkforward.start", walkforward_id=str(walkforward_id))

    async with engine.connect() as conn:
        header = await load_walkforward(conn, walkforward_id)
    if header is None:
        log.error("backtest_worker.walkforward.not_found",
                  walkforward_id=str(walkforward_id))
        return
    if header["status"] != "pending":
        log.warning("backtest_worker.walkforward.not_pending",
                    walkforward_id=str(walkforward_id),
                    status=header["status"])
        return

    async with engine.begin() as conn:
        await mark_walkforward_running(conn, walkforward_id)

    try:
        strategy_name = header["strategy_name"]
        symbols = list(header["symbols"])
        resolution = header["bar_resolution"]
        param_grid = header["param_grid"] or {}

        # Resolve strategy class
        async with session_scope() as session:
            try:
                resolved = await resolve_strategy(
                    session,
                    user_id=header["user_id"],
                    strategy_name=strategy_name,
                    builtin_registry=strategies_cache,
                )
            except StrategyNotFoundError:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} not found in built-ins or user_strategies."
                )
            except StrategyLoadError as e:
                raise RuntimeError(
                    f"Strategy {strategy_name!r} failed to compile: {e}"
                )
        strategy_cls = resolved.cls

        # Load all bars (full history)
        bars: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = await _load_bars(engine, symbol, resolution)
            if df.empty:
                raise RuntimeError(
                    f"No bars available for {symbol!r} at resolution {resolution!r}"
                )
            bars[symbol] = df

        # Run walk-forward orchestration (in-process)
        config = BacktestConfig(
            starting_cash=Decimal(str(header["starting_cash"])),
            fee_rate_bps=int(header["fee_rate_bps"]),
            slippage_bps=int(header["slippage_bps"]),
        )
        result = run_walkforward(
            strategy_cls=strategy_cls,
            symbols=symbols,
            all_bars=bars,
            param_grid=param_grid,
            train_bars=int(header["train_bars"]),
            test_bars=int(header["test_bars"]),
            num_windows=int(header["num_windows"]),
            config=config,
            selection_metric=header["selection_metric"],
        )

        async with engine.begin() as conn:
            await save_walkforward_results(conn, walkforward_id, result)

        log.info("backtest_worker.walkforward.completed",
                 walkforward_id=str(walkforward_id),
                 windows=len(result.windows),
                 duration_s=result.duration_seconds)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\\n\\n{traceback.format_exc()}"
        log.error("backtest_worker.walkforward.failed",
                  walkforward_id=str(walkforward_id),
                  err=str(e))
        try:
            async with engine.begin() as conn:
                await mark_walkforward_failed(conn, walkforward_id, error_msg)
        except Exception as inner_e:
            log.error("backtest_worker.walkforward.cannot_mark_failed",
                      walkforward_id=str(walkforward_id),
                      err=str(inner_e))
'''
    # Insert before "# Main loop" or before async def main_loop
    main_loop_anchor = "async def main_loop"
    if main_loop_anchor in src and "_process_walkforward_job" not in src:
        # Find the comment block right before async def main_loop
        idx = src.find(main_loop_anchor)
        # Walk back over the comment block ("# ===" lines)
        # Just insert before the first "# ==" preceding main_loop
        comment_block_start = src.rfind("# ===", 0, idx)
        if comment_block_start == -1:
            comment_block_start = idx
        src = src[:comment_block_start] + handler_code + "\n\n" + src[comment_block_start:]
    p.write_text(src)
    print("worker: patched")
PY
```

Expected output for each: `patched`. Any `WARN` or `ERROR` means a manual edit is needed — paste those back to me and I'll fix.

### 3. Run the migration

```bash
# Mac → push, then box → apply
git add -A
git status
git commit -m "Step 33 Stage 1: walk-forward backend (orchestration, persistence, API)"
git push

# Box
cd ~/app
git pull
cat migrations/versions/0007_walkforwards.sql | docker exec -i signal_postgres psql -U signal -d signal_platform
```

Should print `CREATE TABLE`, `CREATE INDEX`, `CREATE INDEX`.

### 4. Rebuild and restart

```bash
cd ~/app
docker compose build api backtest_worker
docker compose up -d --force-recreate api backtest_worker
sleep 10
```

### 5. Smoke test via curl

You'll need to grab a fresh auth token. From the browser, open dev tools → Network tab → any API request → copy the `Authorization: Bearer ...` header.

```bash
# Replace YOUR_TOKEN
TOKEN="YOUR_BEARER_TOKEN_HERE"
BASE="https://signal.cimcha.com/api"   # adjust to your API base if different

# Create a walk-forward job
curl -X POST "$BASE/walkforwards" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "SMACrossover",
    "symbols": ["BTC-USDT@BINANCEUS"],
    "bar_resolution": "1d",
    "param_grid": {"slow_period": [30, 50, 100, 150]},
    "train_bars": 180,
    "test_bars": 30,
    "num_windows": 5,
    "selection_metric": "sharpe"
  }'
```

Should return `{"id":"some-uuid", "status":"pending"}`.

Wait ~30 seconds, then fetch the result:

```bash
WF_ID="THE_ID_FROM_ABOVE"
curl -s "$BASE/walkforwards/$WF_ID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

You should see `"status": "completed"` and a `windows_result` array with 5 entries, each showing best_params, train/test sharpe, etc.

## What To Paste Back

The full output of:
1. The patch script (`patched` or `WARN` lines)
2. The migration command (`CREATE TABLE` etc.)
3. The first curl POST response
4. The follow-up GET response (after 30 seconds)

If everything looks good, Stage 2 (frontend) goes in the next round.

## Rollback

If things break and you need to wind back:

```bash
# Drop the table
docker exec -i signal_postgres psql -U signal -d signal_platform -c "DROP TABLE IF EXISTS walkforwards CASCADE;"

# Revert the commit
cd ~/signal-platform
git revert HEAD --no-edit
git push

cd ~/app
git pull
docker compose build api backtest_worker
docker compose up -d --force-recreate api backtest_worker
```
