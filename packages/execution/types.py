"""Execution-layer value types, shared by paper and live brokers.

These intentionally mirror the spirit of the backtest ``Order`` types but are
distinct: backtest orders are simulated inside a single process against a bar
DataFrame, whereas these flow to a broker (real or simulated) and are persisted
in the ``orders`` / ``order_fills`` tables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    """Lifecycle states for a placed order.

    Names map cleanly onto Binance order statuses while staying readable:
      NEW            — accepted, not yet (fully) filled
      PARTIALLY_FILLED
      FILLED
      CANCELED
      REJECTED       — broker/venue refused it
      EXPIRED        — timed out (e.g. IOC remainder)
    """

    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# Statuses that mean the order is done and won't change further.
TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OrderRequest:
    """A request to place a single order."""

    canonical_symbol: str
    native_symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require a limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders must not carry a limit_price")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")


@dataclass(frozen=True)
class FillRecord:
    """One execution against an order."""

    price: Decimal
    quantity: Decimal
    fee: Decimal
    fee_currency: str
    ts: datetime = field(default_factory=_utcnow)
    venue_fill_id: str | None = None


@dataclass(frozen=True)
class OrderResult:
    """The outcome of placing (or querying) an order at the broker."""

    client_order_id: str
    status: OrderStatus
    filled_quantity: Decimal
    avg_fill_price: Decimal | None
    fees: Decimal
    fee_currency: str
    fills: list[FillRecord] = field(default_factory=list)
    venue_order_id: str | None = None
    raw: dict | None = None
    error_message: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class BrokerPosition:
    canonical_symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
