"""Tests for the Polygon data adapter: symbol translation (keeps @ALPACA tag)
and parsing of trade vs aggregate frames into canonical TradeEvents."""
from __future__ import annotations

from decimal import Decimal

import pytest

from packages.adapters.equity.polygon import PolygonDataAdapter
from packages.core.exceptions import AdapterError


def _eq_adapter(channel="aggregates_sec"):
    return PolygonDataAdapter("test-key", channel=channel, cluster="stocks")


def test_symbol_translation_keeps_alpaca_tag():
    a = _eq_adapter()
    assert a.to_canonical_symbol("aapl") == "AAPL@ALPACA"
    assert a.to_native_symbol("MSFT@ALPACA") == "MSFT"
    with pytest.raises(AdapterError):
        a.to_native_symbol("AAPL@POLYGON")  # venue mismatch
    with pytest.raises(AdapterError):
        a.to_native_symbol("AAPL")  # missing suffix


def test_parse_per_second_aggregate():
    a = _eq_adapter(channel="aggregates_sec")
    ev = a._parse_trade(
        {"ev": "A", "sym": "AAPL", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1234, "e": 1700000001000}
    )
    assert ev is not None
    assert ev.canonical_symbol == "AAPL@ALPACA"
    assert ev.price == Decimal("100.5")
    assert ev.quantity == Decimal("1234")
    # wrong event type for this channel -> ignored
    assert a._parse_trade({"ev": "T", "sym": "AAPL", "p": 1, "s": 1, "t": 1700000001000}) is None


def test_parse_trade_channel():
    a = _eq_adapter(channel="trades")
    ev = a._parse_trade(
        {"ev": "T", "sym": "MSFT", "p": 410.25, "s": 50, "t": 1700000002000, "i": "x1"}
    )
    assert ev is not None
    assert ev.canonical_symbol == "MSFT@ALPACA"
    assert ev.price == Decimal("410.25")
    assert ev.venue_trade_id == "x1"


def test_options_cluster_ticker_prefix():
    a = PolygonDataAdapter("k", channel="aggregates_min", cluster="options")
    # option native (OCC) gets the O: prefix on the wire, stripped back on parse
    assert a._native_to_polygon_ticker("AAPL250117C00150000") == "O:AAPL250117C00150000"
    assert a._polygon_ticker_to_native("O:AAPL250117C00150000") == "AAPL250117C00150000"
