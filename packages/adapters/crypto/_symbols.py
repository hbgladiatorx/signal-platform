"""Binance.US symbol-translation helpers shared by the data adapter and broker.

Binance natives have no separator (``BTCUSDT``), so splitting base/quote is
ambiguous without a known quote-asset list. This module centralizes that logic
so the data adapter (``packages/adapters/crypto/binanceus.py``) and the broker
(``packages/broker/binanceus.py``) agree on it.
"""
from __future__ import annotations

VENUE = "BINANCEUS"

# Longest-first so e.g. 'USDT' is matched before 'USD'.
QUOTE_ASSETS: tuple[str, ...] = ("USDT", "USDC", "TUSD", "USD", "BTC", "ETH", "BNB")


def split_native(native: str) -> tuple[str, str]:
    """'BTCUSDT' -> ('BTC', 'USDT'); ('', '') if no known quote suffix."""
    up = native.upper()
    for q in QUOTE_ASSETS:
        if up.endswith(q) and len(up) > len(q):
            return up[: -len(q)], q
    return "", ""


def native_to_canonical(native: str) -> str:
    """'BTCUSDT' -> 'BTC-USDT@BINANCEUS'. Raises ValueError if unsplittable."""
    base, quote = split_native(native)
    if not base:
        raise ValueError(f"cannot split native Binance.US symbol: {native!r}")
    return f"{base}-{quote}@{VENUE}"
