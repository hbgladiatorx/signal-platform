"""Options-chain fetch + normalization shared by the live engine and backtester.

Polygon's options snapshot result shape already matches what
``options.wrapper.select_wrapper`` reads (``details``, ``greeks``,
``implied_volatility``, ``open_interest``, ``day.volume``, ``last_quote``), so
normalization is mostly a pass-through with defensive defaults. Keeping it in one
place means the live engine and the (stage-two) options backtest see identical
chain structure.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable


def normalize_chain(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in raw:
        details = c.get("details", {}) or {}
        out.append({
            "details": {
                "contract_type": details.get("contract_type"),
                "strike_price": details.get("strike_price"),
                "expiration_date": details.get("expiration_date"),
            },
            "greeks": c.get("greeks") or {},
            "implied_volatility": c.get("implied_volatility"),
            "open_interest": c.get("open_interest", 0) or 0,
            "day": {"volume": (c.get("day") or {}).get("volume", 0) or 0},
            "last_quote": {
                "bid": (c.get("last_quote") or {}).get("bid"),
                "ask": (c.get("last_quote") or {}).get("ask"),
            },
        })
    return out


def make_chain_fetcher(polygon_client) -> Callable[[str, date], list[dict[str, Any]]]:
    """Return a fetch(ticker, as_of) -> normalized chain, or [] on failure.

    The live engine and backtester accept this callback so chain access is
    injectable (real client in prod, a stub/fixture in tests).
    """
    def fetch(ticker: str, as_of: date) -> list[dict[str, Any]]:
        if polygon_client is None:
            return []
        try:
            return normalize_chain(polygon_client.options_chain(ticker, as_of))
        except Exception:
            return []
    return fetch
