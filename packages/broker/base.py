"""BrokerAdapter abstract base + normalized data types.

Every brokerage integration implements this interface. The live paper-trading
runner depends only on this abstract class, so adding a broker (or swapping
Alpaca for another) doesn't touch the runner.

Normalized types insulate the platform from broker-specific JSON: adapters
translate their native payloads into these dataclasses, using the platform's
canonical symbols (e.g. 'BTC-USDT@BINANCEUS', 'AAPL@ALPACA') throughout.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from packages.core.types import AssetClass
from packages.strategy.base import OrderSide, OrderType


# Time-in-force values accepted by submit_order. The runner picks the value
# per asset class (see AlpacaBroker); adapters validate what they support.
TimeInForce = str  # "day" | "gtc" | "ioc" | "fok"


@dataclass(frozen=True)
class BrokerOrderRequest:
    """A normalized order to send to the broker."""

    canonical_symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None
    time_in_force: TimeInForce
    client_order_id: str  # deterministic, namespaced (see livetrade.session)


@dataclass(frozen=True)
class BrokerOrder:
    """Normalized view of an order as the broker reports it."""

    broker_order_id: str
    client_order_id: str
    canonical_symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal
    avg_fill_price: Decimal | None
    limit_price: Decimal | None
    status: str  # normalized: new|accepted|partially_filled|filled|canceled|expired|rejected
    submitted_at: datetime | None
    raw: dict[str, Any]  # original payload for audit/debug


@dataclass(frozen=True)
class BrokerPosition:
    """Normalized open position."""

    canonical_symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    market_value: Decimal | None


@dataclass(frozen=True)
class BrokerAccount:
    """Normalized account snapshot."""

    cash: Decimal
    equity: Decimal
    buying_power: Decimal


@dataclass(frozen=True)
class TradeUpdate:
    """Normalized order-lifecycle event from the broker's trade-updates stream."""

    event: str  # new|accepted|fill|partial_fill|canceled|expired|rejected|...
    broker_order_id: str
    client_order_id: str
    canonical_symbol: str
    order_status: str  # normalized order status after this event
    filled_qty: Decimal | None  # cumulative filled qty reported with the event
    fill_qty_delta: Decimal | None  # qty of THIS fill event
    fill_price: Decimal | None
    fee: Decimal
    reason: str | None
    ts: datetime
    raw: dict[str, Any]


class BrokerAdapter(ABC):
    """Abstract base for brokerage execution adapters.

    `paper` reports whether the adapter routes to simulated funds (Alpaca paper)
    or a real exchange. Live adapters (e.g. Binance.US spot, which has no paper
    sandbox) set paper=False; the live-trading runner only constructs those for
    sessions a user explicitly created as mode='live', behind the kill-switch
    and daily-loss guardrails. Callers can assert `paper` before trading.
    """

    venue: str
    paper: bool

    # --- Symbol translation ---
    @abstractmethod
    def to_native_symbol(self, canonical_symbol: str) -> str:
        """Translate a canonical symbol to the broker-native form."""

    @abstractmethod
    def to_canonical_symbol(
        self, native_symbol: str, asset_class: AssetClass
    ) -> str:
        """Translate a broker-native symbol back to canonical form.

        asset_class disambiguates venues where the native symbol alone is
        insufficient (e.g. equity 'AAPL' vs an option contract).
        """

    # --- Execution ---
    @abstractmethod
    async def submit_order(self, req: BrokerOrderRequest) -> BrokerOrder:
        """Submit an order. Idempotent on client_order_id (re-submit is safe)."""

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> None:
        """Request cancellation of an open order. No-op if already terminal."""

    @abstractmethod
    async def get_order(
        self,
        *,
        broker_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrder | None:
        """Fetch a single order by broker id or client id; None if not found."""

    # --- Account / positions ---
    @abstractmethod
    async def list_positions(self) -> list[BrokerPosition]:
        """All open positions in the (paper) account."""

    @abstractmethod
    async def get_account(self) -> BrokerAccount:
        """Current account cash/equity/buying-power snapshot."""

    # --- Streaming ---
    @abstractmethod
    def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """Yield normalized trade-update events.

        Reconnects with backoff internally. This stream has no replay, so the
        consumer should run a REST reconciliation sweep after a reconnect.
        """

    async def is_market_open(self) -> bool:
        """Whether the venue is currently accepting trading. Default: always
        open (correct for 24/7 crypto). Equity adapters override."""
        return True

    async def close(self) -> None:
        """Release any held connections. Default: no-op."""
        return None
