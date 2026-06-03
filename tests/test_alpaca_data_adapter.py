"""AlpacaDataAdapter: symbol mapping, frame splitting, trade/quote parsing."""
from __future__ import annotations

from decimal import Decimal

from packages.adapters.equity.alpaca import AlpacaDataAdapter, _frames, _parse_ts


def _adapter() -> AlpacaDataAdapter:
    return AlpacaDataAdapter("k", "s", feed="iex")


def test_symbol_mapping_round_trip():
    a = _adapter()
    assert a.to_native_symbol("AAPL@ALPACA") == "AAPL"
    assert a.to_canonical_symbol("AAPL") == "AAPL@ALPACA"
    assert a.to_canonical_symbol("aapl") == "AAPL@ALPACA"


def test_frames_handles_array_and_object():
    assert len(_frames('[{"T":"t"},{"T":"q"}]')) == 2
    assert len(_frames('{"T":"t"}')) == 1
    assert _frames("not json") == []


def test_parse_trade():
    a = _adapter()
    ev = a._parse_trade(
        {"T": "t", "S": "AAPL", "p": 192.34, "s": 100,
         "t": "2026-05-31T14:30:00.123456789Z", "i": 42}
    )
    assert ev is not None
    assert ev.canonical_symbol == "AAPL@ALPACA"
    assert ev.price == Decimal("192.34")
    assert ev.quantity == Decimal("100")
    assert ev.venue_trade_id == "42"


def test_parse_trade_ignores_non_trade():
    a = _adapter()
    assert a._parse_trade({"T": "q", "S": "AAPL"}) is None


def test_parse_ts_truncates_nanos():
    dt = _parse_ts("2026-05-31T14:30:00.123456789Z")
    assert dt.microsecond == 123456
    assert dt.tzinfo is not None
