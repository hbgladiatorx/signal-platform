"""Order execution: paper and live trading.

This package adds the execution layer that backtesting alone didn't provide.
It supports two modes against the same instrument universe used everywhere
else on the platform:

  - PAPER: orders fill against the latest known market price in a simulated
    account whose cash/positions live in the database. No external calls,
    no real money.

  - LIVE: orders are transmitted to the venue (Binance.US) via signed REST.
    Live transmission is gated behind an explicit env flag so it can never
    fire by accident.

Public surface:
  - types: ExecutionMode, OrderStatus, OrderRequest, OrderResult, ...
  - base.BrokerAdapter: the interface both brokers implement
  - paper.PaperBroker, binance_broker.BinanceUSLiveBroker
  - manager.TradingManager: routes + persists orders for an account
"""
from packages.execution.base import BrokerAdapter, BrokerError
from packages.execution.types import (
    Balance,
    BrokerPosition,
    ExecutionMode,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Side,
)

__all__ = [
    "BrokerAdapter",
    "BrokerError",
    "Balance",
    "BrokerPosition",
    "ExecutionMode",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Side",
]
