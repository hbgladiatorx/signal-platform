"""AlpacaBroker: symbol mapping, paper-only guard, and no-live-URL safety."""
from __future__ import annotations

import pathlib

import pytest

from packages.broker.alpaca import (
    PAPER_REST_BASE,
    PAPER_STREAM_URL,
    AlpacaBroker,
)
from packages.core.exceptions import ConfigError
from packages.core.types import AssetClass


def _broker() -> AlpacaBroker:
    return AlpacaBroker(api_key_id="k", secret_key="s", paper=True)


def test_paper_false_raises():
    with pytest.raises(ConfigError):
        AlpacaBroker(api_key_id="k", secret_key="s", paper=False)


def test_missing_keys_raise():
    with pytest.raises(ConfigError):
        AlpacaBroker(api_key_id="", secret_key="s", paper=True)


def test_crypto_symbol_mapping_round_trip():
    b = _broker()
    assert b.to_native_symbol("BTC-USDT@BINANCEUS") == "BTC/USD"
    assert (
        b.to_canonical_symbol("BTC/USD", AssetClass.CRYPTO_SPOT)
        == "BTC-USDT@BINANCEUS"
    )


def test_crypto_position_symbol_no_slash():
    # Alpaca's positions API returns 'BTCUSD' (no slash); must still map back.
    b = _broker()
    assert (
        b.to_canonical_symbol("BTCUSD", AssetClass.CRYPTO_SPOT)
        == "BTC-USDT@BINANCEUS"
    )


def test_equity_symbol_mapping_round_trip():
    b = _broker()
    assert b.to_native_symbol("AAPL@ALPACA") == "AAPL"
    assert b.to_canonical_symbol("AAPL", AssetClass.EQUITY) == "AAPL@ALPACA"


def test_urls_are_paper_only():
    assert PAPER_REST_BASE == "https://paper-api.alpaca.markets"
    assert "paper-api.alpaca.markets" in PAPER_STREAM_URL


def test_no_live_alpaca_url_outside_sanctioned_module():
    """Defense in depth: the live trading host may appear ONLY in the
    explicitly-named live broker module (alpaca_live.py). Every other module
    must remain paper-only."""
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in (root / "packages").rglob("*.py"):
        if path.name == "alpaca_live.py":
            continue  # the one sanctioned place for the live host
        text = path.read_text()
        for line in text.splitlines():
            if "api.alpaca.markets" in line and "paper-api.alpaca.markets" not in line:
                offenders.append(f"{path}: {line.strip()}")
    assert not offenders, f"Non-paper Alpaca URL referenced: {offenders}"


def test_paper_module_has_no_live_url():
    """The paper module specifically must never contain the live host."""
    import packages.broker.alpaca as paper_mod

    src = pathlib.Path(paper_mod.__file__).read_text()
    for line in src.splitlines():
        assert not (
            "api.alpaca.markets" in line and "paper-api.alpaca.markets" not in line
        ), f"live URL leaked into paper module: {line.strip()}"


def test_live_broker_uses_live_host_and_is_not_paper():
    from packages.broker.alpaca_live import (
        LIVE_REST_BASE,
        LIVE_STREAM_URL,
        AlpacaLiveBroker,
    )

    assert LIVE_REST_BASE == "https://api.alpaca.markets"
    assert "paper" not in LIVE_STREAM_URL
    b = AlpacaLiveBroker(api_key_id="k", secret_key="s")
    assert b.paper is False
    assert b._rest_base == LIVE_REST_BASE
    # Option/equity symbol translation works on the live broker too.
    assert b.to_native_symbol("AAPL250117C00150000@ALPACA") == "AAPL250117C00150000"
    assert b.to_native_symbol("AAPL@ALPACA") == "AAPL"


def test_live_broker_requires_keys():
    from packages.broker.alpaca_live import AlpacaLiveBroker

    with pytest.raises(ConfigError):
        AlpacaLiveBroker(api_key_id="", secret_key="s")
