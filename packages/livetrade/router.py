"""SessionRegistry + BarRouter.

SessionRegistry is the in-memory index of live sessions this process owns,
plus a routing index from (canonical_symbol, resolution) → session ids.

BarRouter consumes the bars:closed stream once and dispatches each closed bar
to every owning session subscribed to that (symbol, resolution), then acks.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

import structlog

from packages.data.messagebus import (
    GROUP_PAPER_TRADER,
    STREAM_BARS_CLOSED,
    RedisStreamsBus,
)
from packages.livetrade.session import LiveSession

log = structlog.get_logger(__name__)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[UUID, LiveSession] = {}
        self._by_key: dict[tuple[str, str], set[UUID]] = defaultdict(set)
        self._credential: dict[UUID, UUID] = {}  # session_id -> credential_id

    def add(self, session: LiveSession, credential_id: UUID) -> None:
        self._sessions[session.session_id] = session
        self._credential[session.session_id] = credential_id
        for sym in session.symbols:
            self._by_key[(sym, session.resolution)].add(session.session_id)

    def remove(self, session_id: UUID) -> None:
        session = self._sessions.pop(session_id, None)
        self._credential.pop(session_id, None)
        if session is None:
            return
        for sym in session.symbols:
            self._by_key[(sym, session.resolution)].discard(session_id)

    def get(self, session_id: UUID) -> LiveSession | None:
        return self._sessions.get(session_id)

    def all(self) -> list[LiveSession]:
        return list(self._sessions.values())

    def subscribers(self, symbol: str, resolution: str) -> list[LiveSession]:
        ids = self._by_key.get((symbol, resolution), set())
        return [self._sessions[i] for i in ids if i in self._sessions]

    def sessions_for_credential(self, credential_id: UUID) -> list[LiveSession]:
        return [
            s
            for sid, s in self._sessions.items()
            if self._credential.get(sid) == credential_id
        ]

    def credential_ids(self) -> set[UUID]:
        return set(self._credential.values())


class BarRouter:
    """Consumes bars:closed and dispatches to subscribed sessions."""

    def __init__(
        self,
        *,
        bus: RedisStreamsBus,
        registry: SessionRegistry,
        consumer_name: str,
        group: str = GROUP_PAPER_TRADER,
    ) -> None:
        self.bus = bus
        self.registry = registry
        self.consumer_name = consumer_name
        self.group = group
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        # Start from NEW bars only ("$"): a fresh paper_trader must not replay
        # the retained bars:closed history. On restart the group already exists
        # and resumes from its last-delivered id.
        await self.bus.ensure_group(STREAM_BARS_CLOSED, self.group, start_id="$")
        log.info("paper.bar_router.started", group=self.group)
        while not self._stop.is_set():
            try:
                messages = await self.bus.consume(
                    STREAM_BARS_CLOSED,
                    self.group,
                    self.consumer_name,
                    count=200,
                    block_ms=1000,
                )
            except Exception as e:  # noqa: BLE001
                log.error("paper.bar_router.consume_error", error=str(e))
                await asyncio.sleep(1.0)
                continue
            if not messages:
                continue
            ack_ids: list[str] = []
            for msg_id, payload in messages:
                try:
                    await self._dispatch(payload)
                except Exception as e:  # noqa: BLE001
                    log.error("paper.bar_router.dispatch_error", error=str(e))
                ack_ids.append(msg_id)
            # Ack after processing (effectively-once via per-session watermark).
            await self.bus.ack(STREAM_BARS_CLOSED, self.group, ack_ids)

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        if not payload.get("closed"):
            return
        symbol = payload.get("canonical_symbol")
        resolution = payload.get("resolution")
        if not symbol or not resolution:
            return
        subs = self.registry.subscribers(symbol, resolution)
        for session in subs:
            try:
                await session.on_closed_bar(payload)
            except Exception as e:  # noqa: BLE001
                log.error(
                    "paper.bar_router.session_error",
                    session_id=str(session.session_id),
                    error=str(e),
                )
