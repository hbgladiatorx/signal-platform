"""
Redis stream subscriber for the API service.

Runs as an asyncio background task inside the API process. Reads from
the trades:raw and quotes:raw Redis streams and broadcasts events to
all connected WebSocket clients subscribed to the relevant instrument.

This is Architecture A from the Step 11 design: each Gunicorn worker
maintains its own subscriber and its own client set. Two workers means
each event is read from Redis twice — Redis can easily handle this and
it avoids the indirection of a pub/sub fan-out service.

Consumer group: `ws-broadcast` (distinct from `persistence` used by
the persistence_worker). Both groups receive every message via the
Redis Streams XADD/XREADGROUP semantics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections import defaultdict
from typing import Any

import redis.asyncio as redis

from packages.data.messagebus import (
    GROUP_WS_BROADCAST,
    STREAM_QUOTES_RAW,
    STREAM_TRADES_RAW,
)

logger = logging.getLogger(__name__)

# How long to block waiting for new messages from Redis before looping back.
# Short value keeps reconnect/shutdown responsive; long enough to avoid spin.
_XREAD_BLOCK_MS = 5_000

# Max events per XREADGROUP call.
_XREAD_COUNT = 100


class WSBroadcaster:
    """
    Manages active WebSocket subscriptions per canonical symbol and pushes
    Redis stream events to subscribers.
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[Any]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._redis: redis.Redis | None = None
        self._consumer_name = f"api-{socket.gethostname()}-{os.getpid()}"

    async def subscribe(self, symbol: str, websocket: Any) -> None:
        async with self._lock:
            self._subs[symbol].add(websocket)
        logger.info(
            "ws subscribe symbol=%s total=%d",
            symbol,
            len(self._subs[symbol]),
        )

    async def unsubscribe(self, symbol: str, websocket: Any) -> None:
        async with self._lock:
            if symbol in self._subs:
                self._subs[symbol].discard(websocket)
                if not self._subs[symbol]:
                    del self._subs[symbol]

    async def unsubscribe_all(self, websocket: Any) -> None:
        async with self._lock:
            for symbol in list(self._subs.keys()):
                self._subs[symbol].discard(websocket)
                if not self._subs[symbol]:
                    del self._subs[symbol]

    async def start(self, redis_url: str) -> None:
        if self._task is not None:
            return
        self._redis = redis.from_url(redis_url, decode_responses=True)

        # Make sure the consumer group exists on both streams. MKSTREAM
        # creates the stream if it doesn't exist yet; ignored if it does.
        for stream in (STREAM_TRADES_RAW, STREAM_QUOTES_RAW):
            try:
                await self._redis.xgroup_create(
                    stream, GROUP_WS_BROADCAST, id="$", mkstream=True
                )
            except redis.ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

        self._task = asyncio.create_task(self._run(), name="ws-broadcaster")
        logger.info(
            "ws broadcaster started consumer=%s group=%s",
            self._consumer_name,
            GROUP_WS_BROADCAST,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def _run(self) -> None:
        assert self._redis is not None
        streams = {
            STREAM_TRADES_RAW: ">",
            STREAM_QUOTES_RAW: ">",
        }
        while True:
            try:
                resp = await self._redis.xreadgroup(
                    GROUP_WS_BROADCAST,
                    self._consumer_name,
                    streams,
                    count=_XREAD_COUNT,
                    block=_XREAD_BLOCK_MS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("xreadgroup failed; sleeping")
                await asyncio.sleep(1.0)
                continue

            if not resp:
                continue

            for stream_name, entries in resp:
                kind = "trade" if stream_name == STREAM_TRADES_RAW else "quote"
                ack_ids: list[str] = []
                for entry_id, fields in entries:
                    ack_ids.append(entry_id)
                    symbol = fields.get("canonical_symbol")
                    if not symbol:
                        continue
                    await self._fan_out(symbol, kind, fields)
                if ack_ids:
                    try:
                        await self._redis.xack(
                            stream_name, GROUP_WS_BROADCAST, *ack_ids
                        )
                    except Exception:
                        logger.exception("xack failed stream=%s", stream_name)

    async def _fan_out(
        self, symbol: str, kind: str, payload: dict[str, str]
    ) -> None:
        async with self._lock:
            subs = list(self._subs.get(symbol, ()))

        if not subs:
            return

        message = json.dumps({"type": kind, "symbol": symbol, "data": payload})

        # Send to each subscriber; ignore failures (the WS endpoint will
        # clean up dead connections via unsubscribe_all on its own).
        for ws in subs:
            try:
                await ws.send_text(message)
            except Exception:
                logger.debug("ws send failed; will be cleaned up on disconnect")


broadcaster = WSBroadcaster()
