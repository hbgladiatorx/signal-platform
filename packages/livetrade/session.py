"""LiveSession — runs one strategy live against closed bars.

This is the live analog of packages/backtest/engine.run_backtest, but instead
of simulating fills it submits orders to a broker and lets fills arrive
asynchronously (applied by the reconciler). The same Strategy and BarContext
are reused unchanged.

Per closed bar, in the order the backtest engine uses:
  1. idempotency gate (skip redelivered/stale bars)
  2. append bar to bounded in-memory history
  3. expire orders past their bar-count expiry (+ on_order_expired), apply
     queued strategy cancellations
  4. build BarContext from the broker-confirmed account snapshot
  5. strategy.on_bar(ctx)
  6. drain orders/cancellations
  7. persist orders + watermark + strategy_state in ONE transaction, then
     submit to the broker (so a crash before submit re-submits idempotently)

A per-session asyncio.Lock serializes on_bar against reconciler-driven
lifecycle callbacks, so strategy.state is never mutated concurrently.
"""
from __future__ import annotations

import asyncio
import itertools
import traceback
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from collections.abc import Awaitable, Callable

from packages.broker.base import BrokerAdapter, BrokerOrderRequest
from packages.livetrade import persistence as P
from packages.livetrade.bars import load_bars
from packages.livetrade.guards import KillSwitch
from packages.strategy.base import Order, OrderType, Strategy
from packages.strategy.context import BarContext

log = structlog.get_logger(__name__)

# How many warm-start bars to load and how much in-memory history to keep.
DEFAULT_HISTORY_BARS = 500

# time_in_force selection per asset class.
_CRYPTO_ASSET = "crypto_spot"
_OPTION_ASSET = "option"


@dataclass
class PendingOrder:
    """An order the runner has live at the broker (or pending submit)."""

    order: Order
    db_id: UUID
    broker_order_id: str | None = None


class LiveSession:
    def __init__(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        symbols: list[str],
        resolution: str,
        asset_class: str,
        strategy: Strategy,
        broker: BrokerAdapter,
        engine: AsyncEngine,
        max_order_notional: Decimal | None,
        bar_count: int,
        last_processed_bar_ts: datetime | None,
        history_bars: int = DEFAULT_HISTORY_BARS,
        mode: str = "paper",
        max_daily_loss: Decimal | None = None,
        kill_switch: KillSwitch | None = None,
        on_halt: Callable[[UUID, str], Awaitable[None]] | None = None,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.symbols = symbols
        self.resolution = resolution
        self.asset_class = asset_class
        self.strategy = strategy
        self.broker = broker
        self.engine = engine
        self.max_order_notional = max_order_notional
        self.history_bars = history_bars

        # Live-trading guardrails (no-ops for mode='paper').
        self.mode = mode
        self.max_daily_loss = max_daily_loss
        self.kill_switch = kill_switch
        self.on_halt = on_halt
        self._halted = False
        self._halt_reason: str | None = None
        self._day = None  # UTC date the daily-loss baseline was anchored
        self._day_start_equity: Decimal | None = None

        self.bar_count = bar_count
        self.last_processed_bar_ts = last_processed_bar_ts

        self._history: dict[str, pd.DataFrame] = {}
        self._pending: dict[str, PendingOrder] = {}
        self._queued_cancels: set[str] = set()

        # Broker-confirmed snapshot fed into BarContext.
        self._positions: dict[str, Decimal] = {}
        self._cash: Decimal = Decimal(0)

        self.lock = asyncio.Lock()
        self._session8 = session_id.hex[:8]

    # ============================================================
    # Warm start / resume
    # ============================================================
    async def warm_start(self) -> None:
        """Load history, rebuild pending orders, sync the account snapshot."""
        latest_seen: datetime | None = None
        for sym in self.symbols:
            df = await load_bars(
                self.engine, sym, self.resolution, limit=self.history_bars
            )
            self._history[sym] = df
            if not df.empty:
                last = df.index[-1].to_pydatetime()
                if latest_seen is None or last > latest_seen:
                    latest_seen = last

        # Fresh session: anchor the watermark to the newest warm-start bar so we
        # only act on genuinely new bars, never on replayed/old history. A
        # resumed session keeps its persisted watermark.
        if self.last_processed_bar_ts is None and latest_seen is not None:
            self.last_processed_bar_ts = latest_seen

        async with self.engine.connect() as conn:
            open_rows = await P.load_open_orders(conn, self.session_id)
        resubmit: list[Order] = []
        for row in open_rows:
            order = _order_from_row(row)
            self._pending[order.client_order_id] = PendingOrder(
                order=order,
                db_id=row["id"],
                broker_order_id=row.get("broker_order_id"),
            )
            # Committed pre-crash but never sent to the broker → re-submit
            # (idempotent via the deterministic client_order_id).
            if row["status"] == "pending" and not row.get("broker_order_id"):
                resubmit.append(order)
        await self.refresh_account_snapshot()
        for order in resubmit:
            log.info(
                "paper.session.resubmit_pending",
                session_id=str(self.session_id),
                coid=order.client_order_id,
            )
            await self._submit_order(order)

    async def refresh_account_snapshot(self) -> None:
        """Pull authoritative cash/positions from the broker."""
        try:
            account = await self.broker.get_account()
            positions = await self.broker.list_positions()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "paper.session.snapshot_failed",
                session_id=str(self.session_id),
                error=str(e),
            )
            return
        self._cash = account.cash  # buying power view for BarContext.cash
        self._positions = {
            p.canonical_symbol: p.quantity for p in positions if p.quantity != 0
        }
        self._last_equity = account.equity  # used for equity-curve MTM
        self._last_cash = account.cash
        self._check_daily_loss()

    # ============================================================
    # The bar loop
    # ============================================================
    async def on_closed_bar(self, ev: dict[str, Any]) -> None:
        symbol = ev["canonical_symbol"]
        if symbol not in self.symbols:
            return
        bar_ts = datetime.fromtimestamp(int(ev["bucket_start"]), tz=timezone.utc)

        async with self.lock:
            # 1) Drop strictly-stale bars (older than our watermark).
            if (
                self.last_processed_bar_ts is not None
                and bar_ts < self.last_processed_bar_ts
            ):
                return

            # 2) Always fold the closed bar into history (bounded). Doing this
            # before the advance gate means a sibling symbol's bar at an
            # already-advanced bar-time still updates history for future bars.
            self._append_bar(symbol, bar_ts, ev)

            # Idempotency / coalescing gate: only advance + run on_bar once per
            # bar-time. A redelivered bar (==) or a sibling at the same ts that
            # we already advanced past is folded into history above, then skipped.
            if (
                self.last_processed_bar_ts is not None
                and bar_ts <= self.last_processed_bar_ts
            ):
                return

            # 3) Lifecycle BEFORE on_bar (mirror the engine ordering).
            await self._expire_orders()
            await self._apply_queued_cancels()

            # 4) Build the context from the broker-confirmed snapshot.
            seq = itertools.count()
            bar_count = self.bar_count

            def _factory() -> str:
                return f"pt_{self._session8}_{bar_count:05d}_{next(seq)}"

            ctx = BarContext(
                ts=bar_ts,
                symbols=self.symbols,
                history=self._history,
                positions=dict(self._positions),
                cash=self._cash,
                pending_orders=[p.order for p in self._pending.values()],
                bar_count=self.bar_count,
                order_id_factory=_factory,
            )

            # 5) Invoke the strategy (resilient like the engine).
            try:
                self.strategy.on_bar(ctx)
            except Exception as e:  # noqa: BLE001
                log.error(
                    "paper.session.on_bar_error",
                    session_id=str(self.session_id),
                    error=str(e),
                    tb=traceback.format_exc(),
                )

            # 6) Drain.
            new_orders = ctx.collected_orders()
            self._queued_cancels |= ctx.collected_cancellations()

            # 7) Persist (orders + watermark + state) in one tx, then submit.
            await self._persist_advance(bar_ts, new_orders)
            self.bar_count += 1
            self.last_processed_bar_ts = bar_ts

            for order in new_orders:
                await self._submit_order(order)

    def _append_bar(self, symbol: str, bar_ts: datetime, ev: dict[str, Any]) -> None:
        row = {
            "open": float(ev["open"]),
            "high": float(ev["high"]),
            "low": float(ev["low"]),
            "close": float(ev["close"]),
            "volume": float(ev["volume"]),
        }
        df = self._history.get(symbol)
        new_row = pd.DataFrame([row], index=pd.DatetimeIndex([bar_ts], name="bucket"))
        if df is None or df.empty:
            df = new_row
        elif bar_ts in df.index:
            df.loc[bar_ts] = row
        else:
            df = pd.concat([df, new_row])
        # Bound memory.
        if len(df) > self.history_bars:
            df = df.iloc[-self.history_bars :]
        self._history[symbol] = df

    # ============================================================
    # Order submission
    # ============================================================
    async def _persist_advance(self, bar_ts: datetime, new_orders: list[Order]) -> None:
        """Persist new orders (status pending), the watermark, and strategy state
        in a single transaction. Orders that fail the notional check are written
        as 'rejected' and excluded from broker submission."""
        async with self.engine.begin() as conn:
            for order in new_orders:
                rejected = self._notional_rejection(order)
                tif = self._time_in_force(order)
                db_id = await P.insert_paper_order(
                    conn,
                    session_id=self.session_id,
                    client_order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side.value,
                    order_type=order.order_type.value,
                    quantity=order.quantity,
                    limit_price=order.limit_price,
                    time_in_force=tif,
                    bar_count=self.bar_count,
                    expires_at_bar_count=order.expires_at_bar_count,
                    submitted_ts=order.submitted_ts,
                    status="rejected" if rejected else "pending",
                    error_message=rejected,
                )
                if rejected:
                    self._fire_callback("rejected", order, rejected)
                else:
                    self._pending[order.client_order_id] = PendingOrder(
                        order=order, db_id=db_id
                    )
            await P.advance_session_watermark(
                conn,
                self.session_id,
                last_processed_bar_ts=bar_ts,
                last_bar_count=self.bar_count + 1,
                strategy_state_json=dict(self.strategy.state),
            )

    async def _submit_order(self, order: Order) -> None:
        pending = self._pending.get(order.client_order_id)
        if pending is None:  # was rejected pre-submit
            return
        # Live guardrails: refuse to send real-money orders while the global
        # kill-switch is engaged or the session has been halted on daily loss.
        block = await self._live_block_reason()
        if block is not None:
            async with self.engine.begin() as conn:
                await P.mark_order_status(
                    conn, pending.db_id, "rejected", error_message=block
                )
            self._pending.pop(order.client_order_id, None)
            self._fire_callback("rejected", order, block)
            log.warning(
                "paper.session.live_blocked",
                session_id=str(self.session_id),
                coid=order.client_order_id,
                reason=block,
            )
            return
        # Equity guardrail: if the market is closed, Alpaca will queue the
        # order for the next open rather than fill it now — surface that.
        if self.asset_class != _CRYPTO_ASSET:
            try:
                if not await self.broker.is_market_open():
                    log.warning(
                        "paper.session.market_closed_order_queued",
                        session_id=str(self.session_id),
                        coid=order.client_order_id,
                        symbol=order.symbol,
                    )
            except Exception:  # noqa: BLE001
                pass

        req = BrokerOrderRequest(
            canonical_symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            time_in_force=self._time_in_force(order),
            client_order_id=order.client_order_id,
        )
        try:
            result = await self.broker.submit_order(req)
        except Exception as e:  # noqa: BLE001
            log.error(
                "paper.session.submit_failed",
                session_id=str(self.session_id),
                coid=order.client_order_id,
                error=str(e),
            )
            async with self.engine.begin() as conn:
                await P.mark_order_status(
                    conn, pending.db_id, "error", error_message=str(e)
                )
            self._pending.pop(order.client_order_id, None)
            self._fire_callback("rejected", order, f"broker error: {e}")
            return
        pending.broker_order_id = result.broker_order_id
        async with self.engine.begin() as conn:
            await P.set_order_broker_id(
                conn, pending.db_id, result.broker_order_id, result.status
            )

    def _notional_rejection(self, order: Order) -> str | None:
        if self.max_order_notional is None:
            return None
        price = order.limit_price
        if price is None:
            last_close = self._last_close(order.symbol)
            price = last_close
        if price is None:
            return None  # can't evaluate; allow
        # Options are quoted per-share but trade in 100-share contracts.
        notional = order.quantity * price * self._contract_multiplier()
        if notional > self.max_order_notional:
            return (
                f"order notional {notional} exceeds max {self.max_order_notional}"
            )
        return None

    def _contract_multiplier(self) -> Decimal:
        """Contract multiplier for this session's asset class (100 for US
        single-leg options, 1 otherwise)."""
        return Decimal(100) if self.asset_class == _OPTION_ASSET else Decimal(1)

    def _last_close(self, symbol: str) -> Decimal | None:
        df = self._history.get(symbol)
        if df is None or df.empty:
            return None
        return Decimal(str(df["close"].iloc[-1]))

    def _time_in_force(self, order: Order) -> str:
        if self.asset_class == _CRYPTO_ASSET:
            return "gtc"
        # Equities: market must be 'day'; limit GTC unless it has a bar expiry.
        if order.order_type == OrderType.MARKET:
            return "day"
        return "gtc"

    # ============================================================
    # Live guardrails (no-ops for mode='paper')
    # ============================================================
    async def _live_block_reason(self) -> str | None:
        """Return why a live order must NOT be submitted, or None to allow.

        Daily-loss halt is sticky (the session is being torn down); the
        kill-switch only blocks while engaged, so clearing it resumes trading.
        """
        if self.mode != "live":
            return None
        if self._halted:
            return self._halt_reason or "session halted"
        if self.kill_switch is not None and await self.kill_switch.engaged():
            return "global kill-switch engaged"
        return None

    def _check_daily_loss(self) -> None:
        """Halt the session if intraday equity drawdown breaches max_daily_loss.

        Baselines on the first snapshot of each UTC day; on breach, flips the
        sticky halt flag and schedules the runner's halt callback off-lock.
        """
        if self.mode != "live" or self.max_daily_loss is None or self._halted:
            return
        equity = getattr(self, "_last_equity", None)
        if equity is None:
            return
        today = datetime.now(tz=timezone.utc).date()
        if self._day != today or self._day_start_equity is None:
            self._day = today
            self._day_start_equity = equity
            return
        drawdown = self._day_start_equity - equity
        if drawdown > self.max_daily_loss:
            self._halted = True
            self._halt_reason = (
                f"daily-loss halt: intraday drawdown {drawdown} exceeds "
                f"max {self.max_daily_loss}"
            )
            log.warning(
                "paper.session.daily_loss_halt",
                session_id=str(self.session_id),
                drawdown=str(drawdown),
                limit=str(self.max_daily_loss),
            )
            if self.on_halt is not None:
                # Off-lock: _check_daily_loss runs under self.lock.
                asyncio.create_task(self.on_halt(self.session_id, self._halt_reason))

    # ============================================================
    # Expiry + cancellation
    # ============================================================
    async def _expire_orders(self) -> None:
        expired = [
            p
            for p in self._pending.values()
            if p.order.expires_at_bar_count is not None
            and p.order.expires_at_bar_count <= self.bar_count
        ]
        for p in expired:
            if p.broker_order_id:
                try:
                    await self.broker.cancel_order(p.broker_order_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("paper.session.expire_cancel_failed", error=str(e))
            self._pending.pop(p.order.client_order_id, None)
            async with self.engine.begin() as conn:
                await P.mark_order_status(conn, p.db_id, "expired")
            self._fire_callback("expired", p.order, None)

    async def _apply_queued_cancels(self) -> None:
        for coid in list(self._queued_cancels):
            p = self._pending.get(coid)
            self._queued_cancels.discard(coid)
            if p is None:
                continue
            if p.broker_order_id:
                try:
                    await self.broker.cancel_order(p.broker_order_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("paper.session.cancel_failed", error=str(e))
            # Actual removal + on_order_cancelled happens when the broker
            # confirms via trade_updates; but if not yet at broker, drop now.
            if not p.broker_order_id:
                self._pending.pop(coid, None)
                async with self.engine.begin() as conn:
                    await P.mark_order_status(conn, p.db_id, "canceled")
                self._fire_callback("cancelled", p.order, None)

    # ============================================================
    # Reconciler hooks (called under self.lock)
    # ============================================================
    def remove_pending(self, client_order_id: str) -> Order | None:
        p = self._pending.pop(client_order_id, None)
        return p.order if p else None

    def get_pending(self, client_order_id: str) -> PendingOrder | None:
        return self._pending.get(client_order_id)

    def _fire_callback(self, kind: str, order: Order, reason: str | None) -> None:
        try:
            if kind == "rejected":
                self.strategy.on_order_rejected(order, reason or "")
            elif kind == "cancelled":
                self.strategy.on_order_cancelled(order)
            elif kind == "expired":
                self.strategy.on_order_expired(order)
        except Exception as e:  # noqa: BLE001
            log.error(
                "paper.session.callback_error",
                session_id=str(self.session_id),
                kind=kind,
                error=str(e),
            )

    def fire_callback(self, kind: str, order: Order, reason: str | None = None) -> None:
        self._fire_callback(kind, order, reason)


def _order_from_row(row: dict[str, Any]) -> Order:
    """Reconstruct a strategy Order from a paper_orders row (for resume)."""
    from packages.strategy.base import OrderSide

    return Order(
        symbol=row["symbol"],
        side=OrderSide(row["side"]),
        quantity=Decimal(str(row["quantity"])),
        order_type=OrderType(row["order_type"]),
        limit_price=Decimal(str(row["limit_price"]))
        if row.get("limit_price") is not None
        else None,
        submitted_ts=row["submitted_ts"],
        client_order_id=row["client_order_id"],
        expires_at_bar_count=row.get("expires_at_bar_count"),
    )
