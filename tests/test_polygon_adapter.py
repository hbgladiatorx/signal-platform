"""Unit tests for the Polygon adapter translation and message parsing."""
from __future__ import annotations

from decimal import Decimal

import pytest

from packages.adapters.equity.polygon import PolygonAdapter, to_canonical, to_native
from packages.core.exceptions import AdapterError
from packages.core.types import TradeSide  # noqa: F401 (ensures enum import path valid)


def test_symbol_translation_roundtrip():
    assert to_canonical("aapl") == "AAPL-USD@POLYGON"
    assert to_native("AAPL-USD@POLYGON") == "AAPL"


def test_to_native_rejects_wrong_venue():
    with pytest.raises(AdapterError):
        to_native("AAPL-USD@BINANCEUS")
    with pytest.raises(AdapterError):
        to_native("AAPL")  # no @venue


def test_parse_trade():
    adapter = PolygonAdapter(api_key="x")
    event = adapter._parse_trade(
        {"ev": "T", "sym": "AAPL", "p": 190.25, "s": 100, "t": 1_700_000_000_000, "i": "42"}
    )
    assert event is not None
    assert event.canonical_symbol == "AAPL-USD@POLYGON"
    assert event.price == Decimal("190.25")
    assert event.quantity == Decimal("100")
    assert event.venue_trade_id == "42"
    assert event.side is None


def test_parse_trade_ignores_other_events():
    adapter = PolygonAdapter(api_key="x")
    assert adapter._parse_trade({"ev": "status", "message": "connected"}) is None


def test_parse_quote():
    adapter = PolygonAdapter(api_key="x")
    event = adapter._parse_quote(
        {"ev": "Q", "sym": "MSFT", "bp": 410.1, "bs": 5, "ap": 410.2, "as": 3, "t": 1_700_000_000_000}
    )
    assert event is not None
    assert event.canonical_symbol == "MSFT-USD@POLYGON"
    assert event.bid == Decimal("410.1")
    assert event.ask == Decimal("410.2")
    assert event.bid_size == Decimal("5")
    assert event.ask_size == Decimal("3")


def test_adapter_requires_api_key(monkeypatch):
    from packages.core.exceptions import ConfigError

    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        PolygonAdapter()
