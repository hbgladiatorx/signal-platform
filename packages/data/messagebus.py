"""Message bus implementation backed by Redis Streams.

The MessageBus Protocol defines the interface every implementation must
provide. Consumers depend on the Protocol, not on RedisStreamsBus, so a
future backend (Kafka, NATS, etc.) can be swapped in by implementing the
same Protocol.

Streams are persistent and replayable. Each consumer reads via a consumer
group, which gives at-least-once delivery and the ability to scale out by
adding more consumers to the group.

Canonical stream names live at the bottom of this file. Use them rather
than passing string literals.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

import orjson
import redis.asyncio as redis

from packages.core.exceptions import ConfigError


class MessageBus(Protocol):
    """Interface for the platform's message bus.

    Implementations: RedisStreamsBus (Phase 1), future Kafka or NATS.
    """

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        """Publish a JSON-serializable payload. Returns the message ID."""

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Consume up to `count` messages as `consumer` in `group`.

        Returns a list of (message_id, payload) tuples. Blocks up to
        `block_ms` milliseconds waiting for new messages.
        """

    async def ack(
        self,
        stream: str,
        group: str,
        message_ids: list[str],
    ) -> None:
        """Acknowledge delivered messages so they are not redelivered."""

    async def ensure_group(self, stream: str, group: str) -> None:
        """Idempotently ensure a consumer group exists on a stream."""


class RedisStreamsBus:
    """Redis Streams implementation of the MessageBus Protocol.

    The client is created lazily on first use. The stream is bounded with
    XADD MAXLEN ~ 100_000 to prevent unbounded memory growth; old entries
    are evicted when the cap is reached.
    """

    def __init__(self, url: str | None = None) -> None:
        if url is None:
            url = os.environ.get("REDIS_URL")
            if not url:
                raise ConfigError("REDIS_URL is not set in the environment")
        self.url = url
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=False)
        return self._client

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        client = await self._get_client()
        data = {b"payload": orjson.dumps(payload)}
        # MAXLEN with ~ approximates the cap, much faster than exact.
        msg_id = await client.xadd(stream, data, maxlen=100_000, approximate=True)
        return msg_id.decode() if isinstance(msg_id, bytes) else msg_id

    async def ensure_group(self, stream: str, group: str) -> None:
        client = await self._get_client()
        try:
            # mkstream creates the stream if it doesn't exist yet.
            # id="0" means the group starts from the beginning of the stream.
            # For "start from new messages only," use id="$".
            await client.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as e:
            # BUSYGROUP means the group already exists. That's fine.
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, Any]]]:
        client = await self._get_client()
        result = await client.xreadgroup(
            group,
            consumer,
            {stream: ">"},  # ">" means new entries since last delivery
            count=count,
            block=block_ms,
        )
        if not result:
            return []

        messages: list[tuple[str, dict[str, Any]]] = []
        for _stream_name, msgs in result:
            for msg_id, fields in msgs:
                payload = orjson.loads(fields[b"payload"])
                messages.append((msg_id.decode(), payload))
        return messages

    async def ack(
        self,
        stream: str,
        group: str,
        message_ids: list[str],
    ) -> None:
        if not message_ids:
            return
        client = await self._get_client()
        await client.xack(stream, group, *message_ids)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ============================================================
# Canonical stream names
# ============================================================
# Every service should import these constants rather than typing the
# stream name as a string literal. That way renames stay consistent.

STREAM_TRADES_RAW = "trades:raw"
STREAM_QUOTES_RAW = "quotes:raw"
STREAM_BARS_RAW = "bars:raw"

# Canonical consumer group names
GROUP_PERSISTENCE = "persistence"
GROUP_WS_BROADCAST = "ws-broadcast"
