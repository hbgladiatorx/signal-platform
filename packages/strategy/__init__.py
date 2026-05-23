"""Strategy framework.

Public API:

    from packages.strategy import Strategy, BarContext, OrderSide, OrderType, Order
    from packages.strategy import indicators
    from packages.strategy.registry import discover_strategies

Every strategy subclasses `Strategy[P]` where P is a Pydantic params model.
See packages/strategy/base.py for the full contract and strategies/sma_crossover.py
for a worked example.
"""
from packages.strategy.base import Order, OrderSide, OrderType, Strategy
from packages.strategy.context import BarContext

__all__ = [
    "BarContext",
    "Order",
    "OrderSide",
    "OrderType",
    "Strategy",
]
