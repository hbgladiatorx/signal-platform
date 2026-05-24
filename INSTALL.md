# Step 30 — Engine improvements: rejections + cancellation/expiry + partial fills

Three additions to the backtest engine, all opt-in and backward compatible.

## What Changed

### 1. Order lifecycle callbacks on `Strategy`

Three new optional methods, default no-ops:
- `on_order_rejected(order, reason)` — fires when the engine declines to fill (insufficient cash or position)
- `on_order_cancelled(order)` — fires when the strategy-requested cancellation takes effect
- `on_order_expired(order)` — fires when an order's `expires_at_bar_count` is reached

Existing strategies don't need changes; the no-op defaults mean they continue to work exactly as before.

### 2. Order cancellation + expiry

New methods on `BarContext`:
- `cancel_order(client_order_id) -> bool` — request cancellation (takes effect at the start of the NEXT bar's fill phase)
- `pending_orders() -> list[Order]` — snapshot of currently-pending orders

New optional parameter on `submit_*` methods:
- `expires_after_bars: int` — order expires after this many bars without filling

Example use:
```python
def on_bar(self, ctx):
    # A limit buy that expires after 60 bars (1 hour on 1m bars)
    order_id = ctx.submit_buy_limit("BTC-USDT", 0.01, 50000, expires_after_bars=60)
    self.state["pending_id"] = order_id

def on_order_expired(self, order):
    # Reset and try again with looser limit
    if self.state.get("pending_id") == order.client_order_id:
        self.state["pending_id"] = None
```

### 3. Partial fills via volume cap

New optional field on `BacktestConfig`:
- `max_pct_of_volume: Decimal | None = None`

When set (e.g. `0.05`), any single fill is capped at `bar.volume × max_pct_of_volume`. The remainder is requeued for the next bar with the same `client_order_id`. The `Fill` record has `is_partial=True` when this cap engages.

Default is `None` (no cap), so all existing backtests behave exactly as before.

## Files Changed

| File | Change |
|------|--------|
| `packages/strategy/base.py` | Added `Order.expires_at_bar_count`; added 3 lifecycle callbacks to `Strategy` |
| `packages/strategy/context.py` | Added `cancel_order`, `pending_orders`, `expires_after_bars` param, `bar_count` |
| `packages/backtest/types.py` | Added `BacktestConfig.max_pct_of_volume`, `Fill.is_partial`, `BacktestResult.cancelled_orders/expired_orders` |
| `packages/backtest/fills.py` | Volume cap logic + partial-fill remainder return |
| `packages/backtest/engine.py` | Phase 2 rewritten: expirations → cancellations → fills → rejections → callbacks |

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step30-engine-lifecycle.zip
git status
git diff --stat
git add -A
git commit -m "Step 30: order lifecycle callbacks, cancellation/expiry, partial fills"
git push
```

## Deploy (Box)

```bash
cd ~/app
git pull
docker compose build api backtest_worker
docker compose up -d --force-recreate api backtest_worker
sleep 10

# Smoke test: existing strategies still work
docker exec signal_api python -c "
from packages.backtest.types import BacktestConfig
from packages.strategy.base import Order, OrderSide, OrderType
from decimal import Decimal
from datetime import datetime

# Default config — backward compat
c = BacktestConfig()
assert c.max_pct_of_volume is None
print('BacktestConfig default OK')

# Order with optional expiry — backward compat
o1 = Order(symbol='X', side=OrderSide.BUY, quantity=Decimal('1'),
           order_type=OrderType.MARKET, limit_price=None,
           submitted_ts=datetime.now(), client_order_id='a1')
assert o1.expires_at_bar_count is None
print('Order default expiry OK')

# Order with expiry
o2 = Order(symbol='X', side=OrderSide.BUY, quantity=Decimal('1'),
           order_type=OrderType.MARKET, limit_price=None,
           submitted_ts=datetime.now(), client_order_id='a2',
           expires_at_bar_count=42)
assert o2.expires_at_bar_count == 42
print('Order with expiry OK')

print('Smoke test: PASS')
"
```

## Verify End-To-End

### Verify 1: backward compatibility

Run a backtest of an existing built-in strategy (SMACrossover) using the same UI flow. The result should match prior backtests (within deterministic noise — should be identical since defaults are unchanged).

### Verify 2: new callbacks fire

Generate a new strategy via the LLM with this NL description:

> Buy 0.01 BTC every bar where RSI(14) is below 30. Use no cash buffer — issue the order even if cash is insufficient. Track rejections in state.

Then manually edit the saved code to add:
```python
def on_order_rejected(self, order, reason):
    self.state["rejection_count"] = self.state.get("rejection_count", 0) + 1
    self.state["last_rejection_reason"] = reason
```

Run a backtest. After the run, check the backtest detail page — the `strategy_state_final` should show a positive `rejection_count` if any orders were rejected.

### Verify 3: cancellation works

Hand-write a small strategy that submits a limit order then cancels it on the next bar:

```python
def on_bar(self, ctx):
    if "submitted" not in self.state:
        order_id = ctx.submit_buy_limit("BTC-USDT@BINANCEUS", 0.01, 1, expires_after_bars=10)
        self.state["submitted"] = order_id
    elif "cancelled" not in self.state:
        ctx.cancel_order(self.state["submitted"])
        self.state["cancelled"] = True

def on_order_cancelled(self, order):
    self.state["was_cancelled"] = True
```

(The limit price of `1` will never fill, so cancellation is the only outcome.) Run a backtest. `strategy_state_final.was_cancelled` should be `True`.

### Verify 4: expiry works

Same as above but skip the manual cancellation — just let the `expires_after_bars=10` kick in. After 10 bars `on_order_expired` should fire. Add:

```python
def on_order_expired(self, order):
    self.state["was_expired"] = True
```

`strategy_state_final.was_expired` should be `True`.

## Known Limitations

- **LLM prompt not yet updated** to teach Claude about the new features. The LLM will continue to generate strategies using the old API; that's fine since the old API still works. Future polish step: update `packages/strategy/llm_translator.py` system prompt.

- **`max_pct_of_volume` not yet exposed via API/frontend.** Engine supports it; new-backtest form doesn't have a field for it yet. Workaround: edit the DB row directly, or wait for a future step. Defaults to None (off) for now.

- **Persistence of `cancelled_orders` and `expired_orders` is in-memory only.** They're in `BacktestResult` but `save_backtest_results()` doesn't write them to the DB yet. Strategy author sees them via `strategy_state_final` if they tracked them, but they're not viewable on the backtest detail page.

- **Cancellation has a one-bar lag.** A cancel requested in `on_bar(N)` takes effect at the start of `on_bar(N+1)`'s fill phase. So you can't cancel a market order before its fill if you don't decide to cancel until after submitting in the same bar. Workaround: cancel in the same bar you submit (just call `cancel_order(id)` right after `submit_*()`).

## Cleanup Carryover (Updated)

The cleanup carryover items remain. New ones added by this step:
- Update LLM prompt to teach new APIs (callbacks, cancel_order, expires_after_bars)
- Expose `max_pct_of_volume` in API + frontend new-backtest form
- Persist cancelled/expired order records to DB (extend trades table or new tables)
- The `pending_orders` field on BarContext is currently a list snapshot — consider making it cheap to query (the engine already has the list)
