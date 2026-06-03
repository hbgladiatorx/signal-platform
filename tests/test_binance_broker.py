"""Unit tests for the live Binance.US broker: signing, gating, parsing."""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from decimal import Decimal

import pytest

from packages.execution.base import BrokerError
from packages.execution.binance_broker import (
    LIVE_ENABLED_ENV,
    BinanceUSLiveBroker,
    live_trading_enabled,
)
from packages.execution.types import OrderRequest, OrderStatus, OrderType, Side


def test_signing_matches_reference_hmac():
    broker = BinanceUSLiveBroker("key", "secret")
    params = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "1"}
    signed = broker._sign(params)
    query, sig = signed.rsplit("&signature=", 1)
    assert query == urllib.parse.urlencode(params)
    expected = hmac.new(b"secret", query.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


def test_constructor_requires_credentials():
    with pytest.raises(BrokerError):
        BinanceUSLiveBroker("", "secret")


async def test_place_order_blocked_when_live_disabled(monkeypatch):
    monkeypatch.delenv(LIVE_ENABLED_ENV, raising=False)
    assert live_trading_enabled() is False
    broker = BinanceUSLiveBroker("key", "secret")
    req = OrderRequest(
        canonical_symbol="BTC-USDT@BINANCEUS",
        native_symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    with pytest.raises(BrokerError, match="Live trading is disabled"):
        await broker.place_order(req)


def test_live_enabled_flag(monkeypatch):
    monkeypatch.setenv(LIVE_ENABLED_ENV, "true")
    assert live_trading_enabled() is True
    monkeypatch.setenv(LIVE_ENABLED_ENV, "TRUE")
    assert live_trading_enabled() is True
    monkeypatch.setenv(LIVE_ENABLED_ENV, "1")
    assert live_trading_enabled() is False  # only exact "true" counts


def test_parse_filled_market_order():
    payload = {
        "clientOrderId": "abc",
        "orderId": 12345,
        "status": "FILLED",
        "executedQty": "2.0",
        "fills": [
            {"price": "100.0", "qty": "1.0", "commission": "0.1", "commissionAsset": "USDT", "tradeId": 1},
            {"price": "102.0", "qty": "1.0", "commission": "0.1", "commissionAsset": "USDT", "tradeId": 2},
        ],
    }
    result = BinanceUSLiveBroker._parse_order_result("abc", payload)
    assert result.status == OrderStatus.FILLED
    assert result.filled_quantity == Decimal("2.0")
    assert result.avg_fill_price == Decimal("101")  # (100+102)/2 weighted equally
    assert result.fees == Decimal("0.2")
    assert result.fee_currency == "USDT"
    assert result.venue_order_id == "12345"
    assert len(result.fills) == 2


def test_parse_resting_limit_order():
    payload = {"clientOrderId": "abc", "orderId": 7, "status": "NEW", "executedQty": "0"}
    result = BinanceUSLiveBroker._parse_order_result("abc", payload)
    assert result.status == OrderStatus.NEW
    assert result.filled_quantity == Decimal("0")
    assert result.avg_fill_price is None
