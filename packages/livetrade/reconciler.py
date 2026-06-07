"""ReconcilerTask — apply broker trade-updates to the paper_* ledger.

One task per distinct Alpaca account (credential). The account-wide
trade_updates stream is demultiplexed back to sessions via client_order_id.

For each update we (under the owning session's lock, to serialize with on_bar):
  - fill/partial_fill  → insert paper_fills (deduped), update paper_positions
    via the shared average-cost math, advance the order's filled_quantity.
  - canceled/expired/rejected → mark the order, fire the strategy callback.
  - any event          → refresh the broker snapshot + write an equity point.

The trade_updates stream has no replay, so a periodic sweep polls open orders'
state over REST to catch fills missed during a disconnect.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from packages.broker.base import BrokerAdapter, TradeUpdate
from packages.livetrade import persistence as P
from packages.livetrade.position_math import PositionState, apply_buy, apply_sell
from packages.livetrade.session import LiveSession

log = structlog.get_logger(__name__)

_FILL_EVENTS = {"fill", "partial_fill"}
_CANCEL_EVENTS = {"canceled"}
_EXPIRE_EVENTS = {"expired"}
_REJECT_EVENTS = {"rejected"}
SWEEP_INTERVAL_S = 30


class ReconcilerTask:
    """Drives one Alpaca account's trade-updates into the ledger."""

    def __init__(
        self,
        *,
        credential_id: UUID,
        broker: BrokerAdapter,
        engine: Any,
        registry: Any,  # SessionRegistry
    ) -> None:
        self.credential_id = credential_id
        self.broker = broker
        self.engine = engine
        self.registry = registry
        self._stop = asyncio.Event()

    async def run(self) -> None:
        stream_task = asyncio.create_task(self._run_stream())
        sweep_task = asyncio.create_task(self._run_sweep())
        await self._stop.wait()
        stream_task.cancel()
        sweep_task.cancel()
        for t in (stream_task, sweep_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._stop.set()

    # ============================================================
    # Trade-updates stream
    # ============================================================
    async def _run_stream(self) -> None:
        try:
            async for upd in self.broker.stream_trade_updates():
                try:
                    await self._handle_update(upd)
                except Exception as e:  # noqa: BLE001
                    log.error("paper.reconciler.handle_error", error=str(e))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("paper.reconciler.stream_error", error=str(e))

    async def _handle_update(self, upd: TradeUpdate) -> None:
        if not upd.client_order_id:
            return
        async with self.engine.connect() as conn:
            order_row = await P.get_order_by_client_id(conn, upd.client_order_id)
        if order_row is None:
            return  # order not placed by us / unknown
        session_id = order_row["session_id"]
        session = self.registry.get(session_id)

        async def _apply() -> None:
            await self._apply_event(order_row, upd, session)

        if session is not None:
            async with session.lock:
                await _apply()
        else:
            await _apply()

    async def _apply_event(
        self, order_row: dict[str, Any], upd: TradeUpdate, session: LiveSession | None
    ) -> None:
        session_id: UUID = order_row["session_id"]
        order_id: UUID = order_row["id"]
        event = upd.event

        if event in _FILL_EVENTS:
            await self._apply_fill(order_row, upd, session)
        elif event in _CANCEL_EVENTS:
            async with self.engine.begin() as conn:
                await P.mark_order_status(conn, order_id, "canceled")
            self._sync_pending_and_fire(session, order_row, "cancelled", None)
        elif event in _EXPIRE_EVENTS:
            async with self.engine.begin() as conn:
                await P.mark_order_status(conn, order_id, "expired")
            self._sync_pending_and_fire(session, order_row, "expired", None)
        elif event in _REJECT_EVENTS:
            async with self.engine.begin() as conn:
                await P.mark_order_status(
                    conn, order_id, "rejected", error_message=upd.reason
                )
            self._sync_pending_and_fire(session, order_row, "rejected", upd.reason)
        else:
            # new / accepted / pending — just keep broker status in sync.
            if upd.broker_order_id and not order_row.get("broker_order_id"):
                async with self.engine.begin() as conn:
                    await P.set_order_broker_id(
                        conn, order_id, upd.broker_order_id, "accepted"
                    )

        # Snapshot + equity after every event we recognize.
        if session is not None:
            await session.refresh_account_snapshot()
            await self._write_equity_point(session_id, session)

    async def _apply_fill(
        self, order_row: dict[str, Any], upd: TradeUpdate, session: LiveSession | None
    ) -> None:
        session_id: UUID = order_row["session_id"]
        order_id: UUID = order_row["id"]
        symbol = order_row["symbol"]
        side = order_row["side"]
        qty = upd.fill_qty_delta or Decimal(0)
        price = upd.fill_price or Decimal(0)
        if qty <= 0 or price <= 0:
            return

        async with self.engine.begin() as conn:
            inserted = await P.insert_paper_fill(
                conn,
                session_id=session_id,
                order_id=order_id,
                broker_fill_id=str(upd.raw.get("execution_id") or upd.ts.isoformat()),
                symbol=symbol,
                side=side,
                quantity=qty,
                price=price,
                fee=upd.fee,
                filled_ts=upd.ts,
            )
            if not inserted:
                return  # duplicate fill event — already applied

            # Update the event-sourced position ledger.
            positions = await P.load_positions(conn, session_id)
            current = next((p for p in positions if p["symbol"] == symbol), None)
            state = PositionState(
                quantity=Decimal(str(current["quantity"])) if current else Decimal(0),
                avg_cost=Decimal(str(current["avg_cost"])) if current else Decimal(0),
                realized_pnl=Decimal(str(current["realized_pnl"]))
                if current
                else Decimal(0),
            )
            new_state = (
                apply_buy(state, qty, price)
                if side == "buy"
                else apply_sell(state, qty, price, upd.fee)
            )
            await P.upsert_position(
                conn,
                session_id=session_id,
                symbol=symbol,
                quantity=new_state.quantity,
                avg_cost=new_state.avg_cost,
                realized_pnl=new_state.realized_pnl,
            )

            status = "filled" if upd.order_status == "filled" else "partially_filled"
            await P.mark_order_status(
                conn,
                order_id,
                status,
                filled_quantity=upd.filled_qty,
                avg_fill_price=price,
            )

        # On full fill, drop from in-memory pending.
        if session is not None and upd.order_status == "filled":
            session.remove_pending(order_row["client_order_id"])

    def _sync_pending_and_fire(
        self,
        session: LiveSession | None,
        order_row: dict[str, Any],
        kind: str,
        reason: str | None,
    ) -> None:
        if session is None:
            return
        order = session.remove_pending(order_row["client_order_id"])
        if order is not None:
            session.fire_callback(kind, order, reason)

    async def _write_equity_point(
        self, session_id: UUID, session: LiveSession
    ) -> None:
        cash = getattr(session, "_last_cash", session._cash)
        equity = getattr(session, "_last_equity", session._cash)
        positions_value = equity - cash
        async with self.engine.begin() as conn:
            await P.insert_equity_point(
                conn,
                session_id=session_id,
                ts=_now(),
                cash=cash,
                positions_value=positions_value,
                total_equity=equity,
            )
            await P.update_session_summary(conn, session_id, current_equity=equity)

    # ============================================================
    # Periodic REST sweep (covers WS no-replay gaps)
    # ============================================================
    async def _run_sweep(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.sleep(SWEEP_INTERVAL_S)
                # Skip the REST sweep while the venue is closed — no fills can
                # happen, so polling open orders only burns rate limit (the
                # source of the equities 429 storm). Crypto is always-open and
                # keeps sweeping. Fail-open so a clock error doesn't stall it.
                try:
                    if not await self.broker.is_market_open():
                        continue
                except Exception:  # noqa: BLE001
                    pass
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("paper.reconciler.sweep_error", error=str(e))

    async def _sweep_once(self) -> None:
        for session in self.registry.sessions_for_credential(self.credential_id):
            async with self.engine.connect() as conn:
                open_orders = await P.load_open_orders(conn, session.session_id)
            for row in open_orders:
                bid = row.get("broker_order_id")
                if not bid:
                    continue
                bro = await self.broker.get_order(broker_order_id=bid)
                if bro is None:
                    continue
                # If the broker reports more filled than we recorded, the WS
                # likely dropped an event — refresh the snapshot to self-heal.
                recorded = Decimal(str(row.get("filled_quantity") or 0))
                if bro.filled_quantity > recorded or bro.status in (
                    "canceled",
                    "expired",
                    "rejected",
                ):
                    async with session.lock:
                        await session.refresh_account_snapshot()
                        async with self.engine.begin() as conn:
                            await P.mark_order_status(
                                conn,
                                row["id"],
                                bro.status,
                                filled_quantity=bro.filled_quantity,
                                avg_fill_price=bro.avg_fill_price,
                            )
                        if bro.status in ("filled", "canceled", "expired", "rejected"):
                            session.remove_pending(row["client_order_id"])


def _now():  # noqa: ANN202 — small helper
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)
