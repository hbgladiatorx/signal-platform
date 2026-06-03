"""Unit tests for the Binance.US universe loader and adapter translation."""
from __future__ import annotations

import pytest

from packages.adapters.crypto.binance_universe import (
    build_translation_maps,
    canonical_from_parts,
    parse_exchange_info,
)
from packages.adapters.crypto.binanceus import BinanceUSAdapter
from packages.core.exceptions import AdapterError

SAMPLE_EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 8,
        },
        {
            "symbol": "SOLUSD",
            "status": "TRADING",
            "baseAsset": "SOL",
            "quoteAsset": "USD",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 4,
        },
        {
            "symbol": "FOOBAR",
            "status": "BREAK",  # not trading
            "baseAsset": "FOO",
            "quoteAsset": "BAR",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 8,
        },
    ]
}


def test_canonical_from_parts():
    assert canonical_from_parts("sol", "usd") == "SOL-USD@BINANCEUS"


def test_parse_exchange_info_trading_only():
    universe = parse_exchange_info(SAMPLE_EXCHANGE_INFO, trading_only=True)
    natives = {i.native_symbol for i in universe}
    assert natives == {"BTCUSDT", "SOLUSD"}  # FOOBAR excluded (BREAK)


def test_parse_exchange_info_includes_non_trading_when_asked():
    universe = parse_exchange_info(SAMPLE_EXCHANGE_INFO, trading_only=False)
    assert len(universe) == 3


def test_build_translation_maps_roundtrip():
    universe = parse_exchange_info(SAMPLE_EXCHANGE_INFO)
    n2c, c2n = build_translation_maps(universe)
    assert n2c["SOLUSD"] == "SOL-USD@BINANCEUS"
    assert c2n["SOL-USD@BINANCEUS"] == "SOLUSD"


def test_adapter_resolves_after_set_universe():
    adapter = BinanceUSAdapter()
    # Before loading, an exotic pair is unknown.
    with pytest.raises(AdapterError):
        adapter.to_canonical_symbol("SOLUSD")
    adapter.set_universe(parse_exchange_info(SAMPLE_EXCHANGE_INFO))
    assert adapter.to_canonical_symbol("SOLUSD") == "SOL-USD@BINANCEUS"


def test_adapter_fallback_majors_always_resolve():
    adapter = BinanceUSAdapter()
    # The offline fallback covers the two majors even with no universe loaded.
    assert adapter.to_canonical_symbol("BTCUSDT") == "BTC-USDT@BINANCEUS"
    # And remains after a filtered universe that excluded them.
    adapter.set_universe(parse_exchange_info({"symbols": [SAMPLE_EXCHANGE_INFO["symbols"][1]]}))
    assert adapter.to_canonical_symbol("BTCUSDT") == "BTC-USDT@BINANCEUS"


def test_adapter_to_native():
    adapter = BinanceUSAdapter()
    assert adapter.to_native_symbol("SOL-USD@BINANCEUS") == "SOLUSD"
    with pytest.raises(AdapterError):
        adapter.to_native_symbol("SOLUSD")  # missing @venue
