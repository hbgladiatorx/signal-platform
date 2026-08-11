"""PaperTrader — orchestrates live sessions, brokers, reconcilers, and control.

One process owns many sessions. Responsibilities:
  - resume sessions in an active status on startup (warm-start history, rebuild
    pending orders, mark running)
  - one BrokerAdapter + ReconcilerTask per distinct Alpaca credential (shared by
    sessions on that account)
  - BarRouter consuming bars:closed
  - ControlListener consuming paper:control (start / stop / flatten)
  - EquitySnapshotter writing periodic equity points

Sharding (SHARD_INDEX / SHARD_COUNT) lets multiple containers split ownership;
Stage 1 runs a single shard.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.broker.alpaca import AlpacaBroker
from packages.broker.alpaca_live import AlpacaLiveBroker
from packages.broker.base import BrokerAdapter, BrokerOrderRequest
from packages.broker.binanceus import BinanceUSBroker
from packages.core.encryption import decrypt_json
from packages.livetrade.guards import KillSwitch
from packages.data.db import get_engine, session_scope
from packages.data.messagebus import (
    QUEUE_PAPER_CONTROL,
    RedisStreamsBus,
)
from packages.livetrade import persistence as P
from packages.livetrade.reconciler import ReconcilerTask
from packages.livetrade.router import BarRouter, SessionRegistry
from packages.livetrade.session import LiveSession
from packages.strategy.base import OrderSide, OrderType, Strategy
from packages.strategy.resolver import resolve_strategy

log = structlog.get_logger(__name__)

EQUITY_SNAPSHOT_INTERVAL_S = 60
# Liveness cadence — stamped regardless of market hours so the UI can tell a
# worker is alive even when equities are closed. Staleness threshold on the
# frontend should allow a few missed beats (see studio.live.tsx).
HEARTBEAT_INTERVAL_S = 20


class PaperTrader:
    def __init__(
        self,
        *,
        bus: RedisStreamsBus,
        engine: AsyncEngine,
        builtin_registry: dict[str, type[Strategy]],
        worker_name: str,
        shard_index: int = 0,
        shard_count: int = 1,
    ) -> None:
        self.bus = bus
        self.engine = engine
        self.builtin_registry = builtin_registry
        self.worker_name = worker_name
        self.shard_index = shard_index
        self.shard_count = shard_count

        self.registry = SessionRegistry()
        self._brokers: dict[UUID, BrokerAdapter] = {}
        self._reconcilers: dict[UUID, ReconcilerTask] = {}
        self._reconciler_tasks: dict[UUID, asyncio.Task] = {}
        # Global live-trading kill-switch; created in run() once Redis is up.
        self._kill_switch: KillSwitch | None = None

        self._stop = asyncio.Event()
        self._bar_router = BarRouter(
            bus=bus, registry=self.registry, consumer_name=worker_name
        )

    # ============================================================
    # Lifecycle
    # ============================================================
    async def start(self) -> None:
        async with self.engine.connect() as conn:
            rows = await P.load_active_paper_sessions(
                conn, shard_index=self.shard_index, shard_count=self.shard_count
            )
        log.info("paper.runner.resume", count=len(rows))
        for row in rows:
            try:
                await self._load_session(row, resume=True)
            except Exception as e:  # noqa: BLE001
                log.error(
                    "paper.runner.resume_failed",
                    session_id=str(row["id"]),
                    error=str(e),
                )
                async with self.engine.begin() as conn:
                    await P.mark_session_error(conn, row["id"], f"resume failed: {e}")

    async def run(self) -> None:
        # Build the kill-switch reader before resuming sessions so live sessions
        # are gated from their very first bar.
        self._kill_switch = KillSwitch(await self.bus._get_client())
        await self.start()
        tasks = [
            asyncio.create_task(self._bar_router.run(), name="bar-router"),
            asyncio.create_task(self._control_loop(), name="control"),
            asyncio.create_task(self._equity_loop(), name="equity"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
        ]
        await self._stop.wait()
        self._bar_router.stop()
        for r in self._reconcilers.values():
            r.stop()
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for b in self._brokers.values():
            await b.close()

    def stop(self) -> None:
        self._stop.set()

    # ============================================================
    # Session loading
    # ============================================================
    async def _get_broker(self, credential_id: UUID) -> BrokerAdapter:
        if credential_id in self._brokers:
            return self._brokers[credential_id]
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT encrypted_payload, service FROM api_credentials "
                    "WHERE id = :id"
                ),
                {"id": credential_id},
            )
            row = result.mappings().first()
        if row is None:
            raise RuntimeError(f"api_credential {credential_id} not found")
        service = row["service"]
        payload = decrypt_json(bytes(row["encrypted_payload"]))
        if service == "alpaca":
            broker: BrokerAdapter = AlpacaBroker(
                api_key_id=payload["api_key_id"],
                secret_key=payload["secret_key"],
                paper=True,
            )
        elif service == "alpaca_live":
            # REAL MONEY — live Alpaca equities/options. Only sessions created as
            # mode='live' with an alpaca_live credential reach this branch.
            broker = AlpacaLiveBroker(
                api_key_id=payload["api_key_id"],
                secret_key=payload["secret_key"],
            )
        elif service == "binanceus":
            # REAL MONEY — Binance.US spot has no paper sandbox. Only sessions
            # the user created as mode='live' reach this branch (the API only
            # accepts a binanceus credential for a live session).
            broker = BinanceUSBroker(
                api_key=payload["api_key"],
                secret_key=payload["secret_key"],
            )
        else:
            raise RuntimeError(
                f"credential {credential_id} service {service!r} is not a "
                "supported trading venue (expected 'alpaca', 'alpaca_live', or "
                "'binanceus')"
            )
        self._brokers[credential_id] = broker
        # Start a reconciler for this account on first use.
        reconciler = ReconcilerTask(
            credential_id=credential_id,
            broker=broker,
            engine=self.engine,
            registry=self.registry,
        )
        self._reconcilers[credential_id] = reconciler
        self._reconciler_tasks[credential_id] = asyncio.create_task(
            reconciler.run(), name=f"reconciler-{credential_id}"
        )
        return broker

    async def _load_session(self, row: dict[str, Any], *, resume: bool) -> None:
        session_id: UUID = row["id"]
        credential_id: UUID = row["api_credential_id"]
        broker = await self._get_broker(credential_id)

        # Resolve + instantiate the strategy.
        async with session_scope() as db:
            resolved = await resolve_strategy(
                db,
                user_id=row["user_id"],
                strategy_name=row["strategy_name"],
                builtin_registry=self.builtin_registry,
            )
        params = resolved.cls.PARAMS_MODEL(**(row["params_json"] or {}))
        strategy: Strategy = resolved.cls(symbols=list(row["symbols"]), params=params)

        # on_init runs on EVERY load, not just the first start. It sets up derived
        # instance attributes (e.g. self.symbol) that live outside the persisted
        # `state` dict and would otherwise be lost across a restart, crashing
        # on_bar. Run it BEFORE rehydrating state so any persisted state
        # (open-position entry price, counters) overrides on_init's defaults.
        try:
            strategy.on_init()
        except Exception as e:  # noqa: BLE001
            log.error("paper.runner.on_init_error", error=str(e))

        # Rehydrate persisted state across restarts (wins over on_init defaults).
        if row.get("strategy_state_json"):
            strategy.state = dict(row["strategy_state_json"])

        session = LiveSession(
            session_id=session_id,
            user_id=row["user_id"],
            symbols=list(row["symbols"]),
            resolution=row["bar_resolution"],
            asset_class=row["asset_class"],
            strategy=strategy,
            broker=broker,
            engine=self.engine,
            max_order_notional=_dec(row.get("max_order_notional")),
            bar_count=int(row.get("last_bar_count") or 0),
            last_processed_bar_ts=row.get("last_processed_bar_ts"),
            starting_cash=_dec(row.get("starting_cash")) or Decimal(0),
            mode=row.get("mode") or "paper",
            max_daily_loss=_dec(row.get("max_daily_loss")),
            kill_switch=self._kill_switch,
            on_halt=self._halt_session,
        )

        await session.warm_start()
        self.registry.add(session, credential_id)
        async with self.engine.begin() as conn:
            await P.mark_session_running(conn, session_id, initialized=True)
        log.info(
            "paper.runner.session_started",
            session_id=str(session_id),
            strategy=row["strategy_name"],
            symbols=row["symbols"],
            resume=resume,
        )

    # ============================================================
    # Control channel
    # ============================================================
    async def _control_loop(self) -> None:
        import orjson

        redis_client = await self.bus._get_client()  # reuse the bus connection
        while not self._stop.is_set():
            try:
                popped = await redis_client.brpop([QUEUE_PAPER_CONTROL], timeout=5)
            except Exception as e:  # noqa: BLE001
                log.error("paper.runner.control_brpop_error", error=str(e))
                await asyncio.sleep(1.0)
                continue
            if popped is None:
                continue
            _key, value = popped
            try:
                msg = orjson.loads(value)
                await self._handle_control(msg)
            except Exception as e:  # noqa: BLE001
                log.error("paper.runner.control_error", error=str(e), value=value)

    async def _handle_control(self, msg: dict[str, Any]) -> None:
        action = msg.get("action")
        session_id = UUID(msg["session_id"])
        log.info("paper.runner.control", action=action, session_id=str(session_id))
        if action == "start":
            if self.registry.get(session_id) is not None:
                return
            async with self.engine.connect() as conn:
                row = await P.load_paper_session(conn, session_id)
            if row is None:
                return
            if not self._owns(session_id):
                return
            await self._load_session(row, resume=False)
        elif action == "stop":
            await self._stop_session(session_id)
        elif action == "flatten":
            await self._flatten_session(session_id)

    def _owns(self, session_id: UUID) -> bool:
        if self.shard_count <= 1:
            return True
        return int(session_id.int) % self.shard_count == self.shard_index

    async def _stop_session(self, session_id: UUID) -> None:
        session = self.registry.get(session_id)
        async with self.engine.connect() as conn:
            row = await P.load_paper_session(conn, session_id)
        cancel_open = bool(row and row.get("cancel_open_on_stop", True))
        if session is not None and cancel_open:
            async with session.lock:
                for p in list(session._pending.values()):
                    if p.broker_order_id:
                        try:
                            await session.broker.cancel_order(p.broker_order_id)
                        except Exception as e:  # noqa: BLE001
                            log.warning("paper.runner.stop_cancel_failed", error=str(e))
        self.registry.remove(session_id)
        async with self.engine.begin() as conn:
            await P.mark_session_stopped(conn, session_id)

    async def _flatten_session(self, session_id: UUID) -> None:
        session = self.registry.get(session_id)
        if session is None:
            return
        async with session.lock:
            await session.refresh_account_snapshot()
            positions = dict(session._positions)
        for symbol, qty in positions.items():
            if qty <= 0:
                continue
            tif = "gtc" if session.asset_class == "crypto_spot" else "day"
            req = BrokerOrderRequest(
                canonical_symbol=symbol,
                side=OrderSide.SELL,
                quantity=qty,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force=tif,
                client_order_id=f"pt_{session.session_id.hex[:8]}_flatten_{symbol}".replace(
                    "/", "_"
                )[:48],
            )
            try:
                await session.broker.submit_order(req)
            except Exception as e:  # noqa: BLE001
                log.error("paper.runner.flatten_failed", symbol=symbol, error=str(e))

    async def _halt_session(self, session_id: UUID, reason: str) -> None:
        """Permanently halt a live session that tripped a risk guardrail.

        Invoked (as a scheduled task, so it never runs under the session lock)
        when LiveSession's daily-loss check fires. Cancels resting orders, drops
        the session from the registry so no further bars are processed, and marks
        it 'error' with the breach reason. Restarting requires a new session.
        """
        log.warning(
            "paper.runner.session_halted", session_id=str(session_id), reason=reason
        )
        session = self.registry.get(session_id)
        if session is not None:
            for p in list(session._pending.values()):
                if p.broker_order_id:
                    try:
                        await session.broker.cancel_order(p.broker_order_id)
                    except Exception as e:  # noqa: BLE001
                        log.warning("paper.runner.halt_cancel_failed", error=str(e))
        self.registry.remove(session_id)
        async with self.engine.begin() as conn:
            await P.mark_session_error(conn, session_id, reason)

    # ============================================================
    # Equity snapshotter
    # ============================================================
    async def _equity_loop(self) -> None:
        from sqlalchemy.exc import IntegrityError

        while not self._stop.is_set():
            try:
                await asyncio.sleep(EQUITY_SNAPSHOT_INTERVAL_S)
            except asyncio.CancelledError:
                raise
            # Snapshot each session independently so one bad session can't abort
            # the others' snapshot for this tick.
            for session in self.registry.all():
                # Don't poll the broker while its venue is closed (equities
                # overnight/weekends) — that just hammers the REST API and
                # trips rate limits. 24/7 crypto reports always-open and
                # keeps snapshotting. Fail-open so a clock error never
                # silently freezes the equity curve.
                try:
                    if not await session.broker.is_market_open():
                        continue
                except Exception:  # noqa: BLE001
                    pass
                try:
                    async with session.lock:
                        # Keep the broker snapshot fresh for order sizing
                        # (BarContext.cash), but plot the curve from THIS
                        # session's own fills, not the shared account equity.
                        await session.refresh_account_snapshot()
                        cash, pv, equity, realized = (
                            await session.compute_isolated_equity()
                        )
                    async with self.engine.begin() as conn:
                        await P.insert_equity_point(
                            conn,
                            session_id=session.session_id,
                            ts=_now(),
                            cash=cash,
                            positions_value=pv,
                            total_equity=equity,
                        )
                        await P.update_session_summary(
                            conn,
                            session.session_id,
                            current_equity=equity,
                            realized_pnl=realized,
                        )
                except IntegrityError:
                    # The session's paper_sessions row is gone (deleted out from
                    # under the runner, e.g. a DB reset). Stop looping on this
                    # ghost — evict it so we don't FK-violate every 60s forever.
                    self._evict_ghost(session.session_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning("paper.runner.equity_loop_error", error=str(e))

    def _evict_ghost(self, session_id: UUID) -> None:
        """Drop an in-memory session whose DB row no longer exists."""
        self.registry.remove(session_id)
        log.warning("paper.runner.ghost_session_evicted", session_id=str(session_id))

    async def _heartbeat_loop(self) -> None:
        """Prove this worker is alive and owns its sessions. Runs on a fixed
        cadence regardless of market hours (unlike the equity snapshotter), so a
        'running' session with a stale heartbeat means no worker is executing it."""
        while not self._stop.is_set():
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            except asyncio.CancelledError:
                raise
            ids = [s.session_id for s in self.registry.all()]
            if not ids:
                continue
            try:
                async with self.engine.begin() as conn:
                    await P.update_heartbeats(conn, ids)
            except Exception as e:  # noqa: BLE001
                log.warning("paper.runner.heartbeat_error", error=str(e))


def _dec(v: Any) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


def _now():  # noqa: ANN202
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)
