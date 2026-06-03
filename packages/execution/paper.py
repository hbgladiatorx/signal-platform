"""PaperBroker — simulated fills against the latest market price.

Fill model (deliberately simple and transparent):

  - MARKET orders fill immediately and completely at the latest price, adjusted
    by a configurable slippage in basis points (buys pay up, sells receive
    less). A taker fee in bps is charged on notional.

  - LIMIT orders fill immediately *iff* they are already marketable against the
    latest price (buy limit >= price, sell limit <= price). Otherwise they are
    accepted as NEW (resting) and left for a later price to satisfy. Resting
    paper limits are not auto-matched by a background loop in this iteration;
    callers can re-submit or cancel them.

The broker is pure simulation: it never calls a venue. Cash/position effects
are applied by the :class:`TradingManager`, not here — this class only decides
*whether and at what price* an order fills.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from packages.execution.base import BrokerAdapter
from packages.execution.pricing import ChainedPriceSource, PriceSource
from packages.execution.types import (
    Balance,
    BrokerPosition,
    ExecutionMode,
    FillRecord,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

_BPS = Decimal("10000")


class PaperBroker(BrokerAdapter):
    """Simulated broker. Balances/positions are tracked by the manager/DB."""

    mode = ExecutionMode.PAPER

    def __init__(
        self,
        price_source: PriceSource,
        *,
        venue: str = "BINANCEUS",
        fee_bps: int = 10,
        slippage_bps: int = 5,
        quote_currency: str = "USDT",
    ) -> None:
        self.venue = venue
        self._prices = (
            price_source
            if isinstance(price_source, ChainedPriceSource)
            else ChainedPriceSource(price_source)
        )
        self._fee_bps = Decimal(fee_bps)
        self._slippage_bps = Decimal(slippage_bps)
        self._quote_currency = quote_currency

    def _apply_slippage(self, price: Decimal, side: Side) -> Decimal:
        adj = price * self._slippage_bps / _BPS
        return price + adj if side == Side.BUY else price - adj

    def _fee(self, notional: Decimal) -> Decimal:
        return (notional * self._fee_bps / _BPS).quantize(Decimal("0.00000001"))

    async def place_order(self, request: OrderRequest) -> OrderResult:
        coid = request.client_order_id or f"paper-{uuid.uuid4().hex}"
        market_price = await self._prices.require_price(
            request.canonical_symbol, request.native_symbol
        )

        if request.order_type == OrderType.LIMIT:
            assert request.limit_price is not None
            marketable = (
                request.side == Side.BUY and request.limit_price >= market_price
            ) or (
                request.side == Side.SELL and request.limit_price <= market_price
            )
            if not marketable:
                # Accept as a resting order; no fill yet.
                return OrderResult(
                    client_order_id=coid,
                    status=OrderStatus.NEW,
                    filled_quantity=Decimal("0"),
                    avg_fill_price=None,
                    fees=Decimal("0"),
                    fee_currency=self._quote_currency,
                    fills=[],
                    venue_order_id=coid,
                    raw={"simulated": True, "resting": True},
                )
            # Marketable limit fills at the limit price (price improvement
            # ignored for simplicity), no extra slippage.
            fill_price = request.limit_price
        else:
            fill_price = self._apply_slippage(market_price, request.side)

        notional = (fill_price * request.quantity).quantize(Decimal("0.00000001"))
        fee = self._fee(notional)
        fill = FillRecord(
            price=fill_price,
            quantity=request.quantity,
            fee=fee,
            fee_currency=self._quote_currency,
            venue_fill_id=f"{coid}-1",
        )
        return OrderResult(
            client_order_id=coid,
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            avg_fill_price=fill_price,
            fees=fee,
            fee_currency=self._quote_currency,
            fills=[fill],
            venue_order_id=coid,
            raw={"simulated": True, "market_price": str(market_price)},
        )

    async def cancel_order(
        self,
        *,
        native_symbol: str,
        venue_order_id: str | None,
        client_order_id: str,
    ) -> OrderResult:
        # A resting paper order is canceled with no fills.
        return OrderResult(
            client_order_id=client_order_id,
            status=OrderStatus.CANCELED,
            filled_quantity=Decimal("0"),
            avg_fill_price=None,
            fees=Decimal("0"),
            fee_currency=self._quote_currency,
            venue_order_id=venue_order_id or client_order_id,
            raw={"simulated": True, "canceled": True},
        )

    async def get_balances(self) -> list[Balance]:
        # Paper balances are tracked in the DB by the manager, not here.
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        return []
