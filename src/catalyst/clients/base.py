"""Thin HTTP client base: caching, retry, and rate-limit backoff (Section 2).

Each provider client subclasses this. The base is deliberately offline-safe:
if ``requests`` is unavailable or no API key is configured, ``get_json`` raises
``ProviderUnavailable`` rather than fabricating data -- callers degrade
gracefully (the live engine flags missing inputs; the backtester reads from the
already-materialized panel and never hits the network).
"""

from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path
from typing import Any


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot be reached or is not configured.

    Never swallowed into fake data -- that would violate PIT integrity.
    """


class CacheStore:
    """Simple on-disk JSON cache keyed by a hash of (url, params)."""

    def __init__(self, root: str | Path, ttl_seconds: int):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.root / f"{digest}.json"

    def get(self, key: str, now: float) -> Any | None:
        p = self._path(key)
        if not p.exists():
            return None
        if now - p.stat().st_mtime > self.ttl:
            return None
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._path(key).write_text(json.dumps(value))
        except (TypeError, OSError):
            pass


class BaseClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        cache: CacheStore | None = None,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        user_agent: str = "catalyst-breakout",
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.user_agent = user_agent
        self._clock = clock
        self._sleep = sleep

    # -- overridable hooks -------------------------------------------------
    def _auth_params(self) -> dict[str, str]:
        return {}

    def _auth_headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent}

    # -- core --------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        params.update(self._auth_params())
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

        cache_key = json.dumps({"u": url, "p": params}, sort_keys=True)
        if self.cache is not None:
            hit = self.cache.get(cache_key, now=time.time())
            if hit is not None:
                return hit

        data = self._request_with_retry(url, params)

        if self.cache is not None:
            self.cache.set(cache_key, data)
        return data

    def _request_with_retry(self, url: str, params: dict[str, Any]) -> Any:
        try:
            import requests  # imported lazily so the core stays import-light
        except ImportError as e:  # pragma: no cover - env without requests
            raise ProviderUnavailable(f"requests not installed: {e}") from e

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(
                    url, params=params, headers=self._auth_headers(), timeout=30
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    self._backoff(attempt, resp)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # network errors, JSON errors
                last_exc = e
                self._backoff(attempt, None)
        raise ProviderUnavailable(
            f"GET {url} failed after {self.max_retries} retries: {last_exc}"
        )

    def _backoff(self, attempt: int, resp) -> None:
        delay = min(self.backoff_base * (2 ** attempt), self.backoff_max)
        # Honor Retry-After when the server provides it.
        if resp is not None:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    delay = max(delay, float(ra))
                except ValueError:
                    pass
        self._sleep(delay)


def env_key(name: str) -> str | None:
    return os.environ.get(name) or None
