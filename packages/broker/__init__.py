"""Broker / execution adapters.

Where packages/adapters provides market-DATA adapters (AssetAdapter: live
trade/quote streams), this package provides EXECUTION adapters: submitting
orders, tracking fills, and reading account/positions from a brokerage.

The platform only ever constructs PAPER brokers — every adapter guards against
being pointed at a live trading endpoint.
"""
from packages.broker.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    TradeUpdate,
)

__all__ = [
    "BrokerAccount",
    "BrokerAdapter",
    "BrokerOrder",
    "BrokerOrderRequest",
    "BrokerPosition",
    "TradeUpdate",
]
