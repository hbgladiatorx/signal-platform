"""Tests for SymbolRegistry, the Binance.US symbol helpers, and the adapter's
registry-backed translation (which removes the old 2-pair cap)."""
from __future__ import annotations

import pytest

from packages.adapters.crypto import _symbols
from packages.adapters.crypto.binanceus import BinanceUSAdapter
from packages.core.exceptions import AdapterError
from packages.data.symbol_registry import InstrumentRow, SymbolRegistry


def _rows() -> list[InstrumentRow]:
    return [
        InstrumentRow(1, "crypto_spot", "BTC-USDT@BINANCEUS", "BINANCEUS", "BTCUSDT", "BTC", "USDT"),
        InstrumentRow(2, "crypto_spot", "ETH-USDT@BINANCEUS", "BINANCEUS", "ETHUSDT", "ETH", "USDT"),
        InstrumentRow(3, "crypto_spot", "SOL-USD@BINANCEUS", "BINANCEUS", "SOLUSD", "SOL", "USD"),
        InstrumentRow(9, "equity", "AAPL@ALPACA", "ALPACA", "AAPL", "AAPL", "USD"),
    ]


# --- SymbolRegistry ---------------------------------------------------------


def test_registry_bidirectional_mapping():
    reg = SymbolRegistry(_rows())
    assert reg.to_canonical("BTCUSDT", "BINANCEUS") == "BTC-USDT@BINANCEUS"
    assert reg.to_canonical("solusd", "binanceus") == "SOL-USD@BINANCEUS"  # case-insensitive
    assert reg.to_native("ETH-USDT@BINANCEUS") == "ETHUSDT"
    assert reg.instrument_id("SOL-USD@BINANCEUS") == 3
    assert reg.instrument_id("NOPE@BINANCEUS") is None


def test_registry_or_none_and_venue_filter():
    reg = SymbolRegistry(_rows())
    assert reg.to_canonical_or_none("ZZZ", "BINANCEUS") is None
    assert reg.to_canonical_or_none("AAPL", "ALPACA") == "AAPL@ALPACA"
    crypto = reg.canonicals_for_venue("BINANCEUS")
    assert set(crypto) == {"BTC-USDT@BINANCEUS", "ETH-USDT@BINANCEUS", "SOL-USD@BINANCEUS"}
    assert reg.canonicals_for_venue("ALPACA") == ["AAPL@ALPACA"]
    assert len(reg) == 4


# --- _symbols helper --------------------------------------------------------


@pytest.mark.parametrize(
    "native,expected",
    [
        ("BTCUSDT", ("BTC", "USDT")),
        ("ETHBTC", ("ETH", "BTC")),
        ("SOLUSD", ("SOL", "USD")),
        ("DOGEUSDC", ("DOGE", "USDC")),
    ],
)
def test_split_native(native, expected):
    assert _symbols.split_native(native) == expected


def test_native_to_canonical_and_failure():
    assert _symbols.native_to_canonical("ADAUSDT") == "ADA-USDT@BINANCEUS"
    with pytest.raises(ValueError):
        _symbols.native_to_canonical("XYZ")  # no known quote suffix


# --- adapter translation (no longer capped to BTC/ETH) ----------------------


def test_adapter_to_native_any_pair():
    a = BinanceUSAdapter()
    assert a.to_native_symbol("SOL-USDT@BINANCEUS") == "SOLUSDT"
    with pytest.raises(AdapterError):
        a.to_native_symbol("AAPL@ALPACA")  # venue mismatch
    with pytest.raises(AdapterError):
        a.to_native_symbol("BTCUSDT")  # missing venue suffix


def test_adapter_to_canonical_fallback_uncapped():
    a = BinanceUSAdapter()  # no registry -> mechanical fallback
    # The old code raised on anything but BTCUSDT/ETHUSDT; now it resolves.
    assert a.to_canonical_symbol("DOGEUSDT") == "DOGE-USDT@BINANCEUS"
    assert a.to_canonical_symbol("ADAUSD") == "ADA-USD@BINANCEUS"
    with pytest.raises(AdapterError):
        a.to_canonical_symbol("XYZ")  # unsplittable


def test_adapter_prefers_registry():
    reg = SymbolRegistry(_rows())
    a = BinanceUSAdapter(registry=reg)
    assert a.to_canonical_symbol("BTCUSDT") == "BTC-USDT@BINANCEUS"
    # Not in registry -> mechanical fallback still works.
    assert a.to_canonical_symbol("LINKUSDT") == "LINK-USDT@BINANCEUS"
