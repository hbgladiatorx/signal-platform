"""Live-trading guardrails.

Two mechanisms gate REAL-MONEY (mode='live') order submission. Paper sessions
are never affected.

  KillSwitch       — a single platform-wide Redis flag. While engaged, the live
                     runner refuses to submit any live order; it does NOT error
                     the session, so clearing the flag resumes trading on the
                     next bar. Toggled by the API, read (cached) by the runner.

  Daily-loss halt  — a per-session intraday equity-drawdown limit enforced in
                     LiveSession; on breach the session is permanently halted
                     (status='error'). See LiveSession._check_daily_loss.

The kill-switch fails SAFE: if Redis is unreachable and we have no recent known
value, we treat it as engaged rather than risk trading blind.
"""
from __future__ import annotations

import time

import structlog

log = structlog.get_logger(__name__)

# Platform-wide kill-switch flag. Presence of the key == engaged.
KILL_SWITCH_KEY = "live:killswitch"


class KillSwitch:
    """Cached reader of the global kill-switch Redis flag."""

    def __init__(self, redis_client, *, cache_ttl_s: float = 1.0) -> None:
        self._redis = redis_client
        self._ttl = cache_ttl_s
        self._cache: tuple[float, bool] | None = None

    async def engaged(self) -> bool:
        now = time.monotonic()
        if self._cache is not None and now - self._cache[0] < self._ttl:
            return self._cache[1]
        try:
            engaged = bool(await self._redis.exists(KILL_SWITCH_KEY))
        except Exception as e:  # noqa: BLE001
            # Fail safe: keep the last known state, or halt if we never read it.
            engaged = self._cache[1] if self._cache is not None else True
            log.warning("live.killswitch.read_failed", error=str(e), assumed=engaged)
        self._cache = (now, engaged)
        return engaged
