"""Unit tests for the PaperBroker fill model."""
from __future__ import annotations

from decimal import Decimal

import pytest

from packages.execution.paper import PaperBroker
from packages.execution.types import OrderRequest, OrderStatus, OrderType, Side


class FixedPriceSource:
    def __init__(self, price: Decimal) -> None:
        self.price = price

    async def get_price(self, canonical_symbol: str, native_symbol: str) -> Decimal:
        return self.price


def _req(side: Side, otype: OrderType, qty="1", limit=None) -> OrderRequest:
    return OrderRequest(
        canonical_symbol="BTC-USDT@BINANCEUS",
        native_symbol="BTCUSDT",
        side=side,
        order_type=otype,
        quantity=Decimal(qty),
        limit_price=Decimal(limit) if limit is not None else None,
    )


async def test_market_buy_fills_with_slippage_and_fee():
    broker = PaperBroker(FixedPriceSource(Decimal("100")), fee_bps=10, slippage_bps=50)
    result = await broker.place_order(_req(Side.BUY, OrderType.MARKET, "2"))
    assert result.status == OrderStatus.FILLED
    # 50 bps slippage on a buy → 100 * 1.005 = 100.5
    assert result.avg_fill_price == Decimal("100.5")
    assert result.filled_quantity == Decimal("2")
    # fee = 10 bps of notional (100.5 * 2 = 201) = 0.201
    assert result.fees == Decimal("0.20100000")


async def test_market_sell_slips_down():
    broker = PaperBroker(FixedPriceSource(Decimal("100")), fee_bps=0, slippage_bps=100)
    result = await broker.place_order(_req(Side.SELL, OrderType.MARKET))
    assert result.avg_fill_price == Decimal("99")


async def test_marketable_limit_buy_fills_at_limit():
    broker = PaperBroker(FixedPriceSource(Decimal("100")), fee_bps=0, slippage_bps=0)
    # Buy limit above market is immediately marketable; fills at the limit price.
    result = await broker.place_order(_req(Side.BUY, OrderType.LIMIT, "1", "105"))
    assert result.status == OrderStatus.FILLED
    assert result.avg_fill_price == Decimal("105")


async def test_non_marketable_limit_rests():
    broker = PaperBroker(FixedPriceSource(Decimal("100")), fee_bps=0, slippage_bps=0)
    # Buy limit below market does not fill yet.
    result = await broker.place_order(_req(Side.BUY, OrderType.LIMIT, "1", "95"))
    assert result.status == OrderStatus.NEW
    assert result.filled_quantity == Decimal("0")
    assert result.fills == []


async def test_cancel_returns_canceled():
    broker = PaperBroker(FixedPriceSource(Decimal("100")))
    result = await broker.cancel_order(
        native_symbol="BTCUSDT", venue_order_id="x", client_order_id="c"
    )
    assert result.status == OrderStatus.CANCELED


def test_order_request_validation():
    with pytest.raises(ValueError):
        _req(Side.BUY, OrderType.LIMIT, "1")  # limit without price
    with pytest.raises(ValueError):
        _req(Side.BUY, OrderType.MARKET, "1", "100")  # market with price
    with pytest.raises(ValueError):
        _req(Side.BUY, OrderType.MARKET, "0")  # non-positive qty
