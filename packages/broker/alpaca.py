"""Alpaca PAPER-trading broker adapter.

PAPER ONLY. The REST and WebSocket base URLs are hardcoded to the paper
endpoints and the constructor refuses `paper=False`. There is no live-trading
URL anywhere in this module — a grep test enforces that. Live trading lives in
the separate, explicitly-named ``packages/broker/alpaca_live.py``.

Shared execution logic lives in ``packages/broker/_alpaca_common.py``.
"""
from __future__ import annotations

from packages.broker._alpaca_common import BaseAlpacaBroker
from packages.core.exceptions import ConfigError

# Hardcoded PAPER endpoints. Do NOT add live URLs to this module.
PAPER_REST_BASE = "https://paper-api.alpaca.markets"
PAPER_STREAM_URL = "wss://paper-api.alpaca.markets/stream"


class AlpacaBroker(BaseAlpacaBroker):
    """Alpaca paper-account execution adapter (paper-only)."""

    def __init__(
        self,
        api_key_id: str,
        secret_key: str,
        *,
        paper: bool = True,
    ) -> None:
        if not paper:
            raise ConfigError(
                "AlpacaBroker is paper-only; live trading is not supported. "
                "Use AlpacaLiveBroker (packages/broker/alpaca_live.py)."
            )
        super().__init__(
            api_key_id,
            secret_key,
            rest_base=PAPER_REST_BASE,
            stream_url=PAPER_STREAM_URL,
            paper=True,
        )
