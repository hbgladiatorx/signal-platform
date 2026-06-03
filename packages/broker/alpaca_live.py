"""Alpaca LIVE-trading broker adapter — REAL MONEY.

This is the ONLY module permitted to reference the live Alpaca host. It places
real orders (equities and single-leg options) against the live trading API.
Guardrails (global kill-switch, per-session daily-loss halt, max order notional)
are enforced upstream in the livetrade session/runner for any mode='live'
session; this adapter is the execution surface only.

Shared logic lives in ``packages/broker/_alpaca_common.py``.
"""
from __future__ import annotations

import structlog

from packages.broker._alpaca_common import BaseAlpacaBroker
from packages.core.exceptions import ConfigError

log = structlog.get_logger(__name__)

# Live trading endpoints (real money). Permitted here and nowhere else.
LIVE_REST_BASE = "https://api.alpaca.markets"
LIVE_STREAM_URL = "wss://api.alpaca.markets/stream"


class AlpacaLiveBroker(BaseAlpacaBroker):
    """Alpaca live-account execution adapter (REAL MONEY)."""

    def __init__(self, api_key_id: str, secret_key: str) -> None:
        if not api_key_id or not secret_key:
            raise ConfigError("AlpacaLiveBroker requires api_key_id and secret_key.")
        super().__init__(
            api_key_id,
            secret_key,
            rest_base=LIVE_REST_BASE,
            stream_url=LIVE_STREAM_URL,
            paper=False,
        )
        log.warning("alpaca_live.REAL_MONEY", msg="AlpacaLiveBroker active — live orders place real trades")
