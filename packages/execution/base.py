"""BrokerAdapter — the interface paper and live execution share.

A broker takes an :class:`OrderRequest`, does whatever it does (simulate or
transmit), and returns an :class:`OrderResult`. The :class:`TradingManager`
depends only on this interface, so routing between paper and live is a matter
of constructing the right broker.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.exceptions import SignalPlatformError
from packages.execution.types import (
    Balance,
    BrokerPosition,
    ExecutionMode,
    OrderRequest,
    OrderResult,
)


class BrokerError(SignalPlatformError):
    """Raised when a broker cannot place, cancel, or query an order."""


class BrokerAdapter(ABC):
    """Abstract broker. Implementations: PaperBroker, BinanceUSLiveBroker."""

    mode: ExecutionMode
    venue: str

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Place an order and return its (possibly partial) result."""

    @abstractmethod
    async def cancel_order(
        self,
        *,
        native_symbol: str,
        venue_order_id: str | None,
        client_order_id: str,
    ) -> OrderResult:
        """Cancel a resting order. Returns the order's resulting state."""

    @abstractmethod
    async def get_balances(self) -> list[Balance]:
        """Return current account balances."""

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """Return current open positions (best-effort for spot venues)."""

    async def close(self) -> None:
        """Release any resources (HTTP sessions). Default no-op."""
        return None
