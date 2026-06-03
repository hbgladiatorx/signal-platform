"""BinanceUSBroker: symbol mapping, id packing, precision, and event parsing.

All pure/cached logic — no network. The live REST/WS paths are exercised
manually against the real exchange (there is no Binance.US sandbox).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from packages.broker.binanceus import (
    REST_BASE,
    VENUE,
    BinanceUSBroker,
    _pack_broker_id,
    _split_native,
    _unpack_broker_id,
)
from packages.core.exceptions import ConfigError
from packages.strategy.base import OrderSide, OrderType


def _broker() -> BinanceUSBroker:
    return BinanceUSBroker(api_key="k", secret_key="s")


# ============================================================
# Construction
# ============================================================
def test_missing_keys_raise():
    with pytest.raises(ConfigError):
        BinanceUSBroker(api_key="", secret_key="s")
    with pytest.raises(ConfigError):
        BinanceUSBroker(api_key="k", secret_key="")


def test_is_live_not_paper():
    # Binance.US spot is real money — paper must be False, and the REST host
    # must be the live exchange (there is no paper host to confuse it with).
    assert _broker().paper is False
    assert REST_BASE == "https://api.binance.us"
    assert VENUE == "BINANCEUS"


# ============================================================
# Symbol translation
# ============================================================
def test_symbol_round_trip():
    b = _broker()
    assert b.to_native_symbol("BTC-USDT@BINANCEUS") == "BTCUSDT"
    assert b.to_canonical_symbol("BTCUSDT") == "BTC-USDT@BINANCEUS"


def test_symbol_venue_mismatch_rejected():
    from packages.core.exceptions import AdapterError

    b = _broker()
    with pytest.raises(AdapterError):
        b.to_native_symbol("AAPL@ALPACA")
    with pytest.raises(AdapterError):
        b.to_native_symbol("BTCUSDT")  # missing @venue


def test_split_native():
    assert _split_native("BTCUSDT") == ("BTC", "USDT")
    assert _split_native("ETHUSD") == ("ETH", "USD")
    assert _split_native("ETHBTC") == ("ETH", "BTC")
    assert _split_native("WAT") == ("", "")


# ============================================================
# broker_order_id packing (symbol is required to cancel/get on Binance)
# ============================================================
def test_broker_id_pack_unpack():
    assert _pack_broker_id("BTCUSDT", 4293153) == "BTCUSDT:4293153"
    assert _unpack_broker_id("BTCUSDT:4293153") == ("BTCUSDT", "4293153")
    assert _unpack_broker_id("garbage") == (None, None)


# ============================================================
# exchangeInfo precision (uses the pre-seeded filter cache; no network)
# ============================================================
async def test_round_qty_and_price():
    b = _broker()
    b._filters["BTCUSDT"] = {
        "step": Decimal("0.001"),
        "tick": Decimal("0.01"),
        "min_qty": Decimal("0.001"),
    }
    # Quantity floors to the step (never request more than intended).
    assert await b._round_qty("BTCUSDT", Decimal("0.0034999")) == Decimal("0.003")
    # Price rounds to nearest tick.
    assert await b._round_price("BTCUSDT", Decimal("100.017")) == Decimal("100.02")


async def test_round_no_filters_is_passthrough():
    b = _broker()
    b._filters["XYZUSDT"] = {}  # cached empty → no rounding
    assert await b._round_qty("XYZUSDT", Decimal("1.23456789")) == Decimal("1.23456789")


# ============================================================
# executionReport parsing (the user-data WS event)
# ============================================================
def _exec_report(**over):
    base = {
        "e": "executionReport",
        "s": "BTCUSDT",
        "c": "mycoid",
        "S": "BUY",
        "o": "LIMIT",
        "q": "1.00000000",
        "p": "20000.00",
        "x": "TRADE",
        "X": "PARTIALLY_FILLED",
        "i": 4293153,
        "l": "0.50000000",
        "z": "0.50000000",
        "L": "19999.50",
        "n": "0.01000000",
        "N": "USDT",
        "T": 1499405658657,
        "t": 148,
        "C": "",
    }
    base.update(over)
    return base


def test_parse_partial_fill():
    b = _broker()
    upd = b._parse_execution_report(_exec_report())
    assert upd is not None
    assert upd.event == "partial_fill"
    assert upd.canonical_symbol == "BTC-USDT@BINANCEUS"
    assert upd.broker_order_id == "BTCUSDT:4293153"
    assert upd.client_order_id == "mycoid"
    assert upd.filled_qty == Decimal("0.5")
    assert upd.fill_qty_delta == Decimal("0.5")
    assert upd.fill_price == Decimal("19999.50")
    assert upd.fee == Decimal("0.01")
    assert upd.order_status == "partially_filled"
    # The reconciler dedups fills on this key.
    assert upd.raw["execution_id"] == "148"


def test_parse_full_fill():
    b = _broker()
    upd = b._parse_execution_report(_exec_report(X="FILLED", z="1.00000000"))
    assert upd.event == "fill"
    assert upd.order_status == "filled"


def test_parse_cancel_uses_original_coid():
    b = _broker()
    upd = b._parse_execution_report(
        _exec_report(x="CANCELED", X="CANCELED", c="cancel-req", C="orig-coid")
    )
    assert upd.event == "canceled"
    assert upd.order_status == "canceled"
    # Must match the order we placed (original client id), not the cancel id.
    assert upd.client_order_id == "orig-coid"


# ============================================================
# REST order response parsing
# ============================================================
def test_parse_order_market_avg_from_quote():
    b = _broker()
    o = {
        "symbol": "BTCUSDT",
        "orderId": 28,
        "clientOrderId": "abc",
        "side": "BUY",
        "type": "MARKET",
        "origQty": "0.10000000",
        "executedQty": "0.10000000",
        "cummulativeQuoteQty": "2000.00",
        "status": "FILLED",
        "transactTime": 1507725176595,
    }
    order = b._parse_order(o)
    assert order.broker_order_id == "BTCUSDT:28"
    assert order.side == OrderSide.BUY
    assert order.order_type == OrderType.MARKET
    assert order.filled_quantity == Decimal("0.1")
    assert order.avg_fill_price == Decimal("20000.00")
    assert order.status == "filled"
