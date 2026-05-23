"""Strategy framework — base class and core types.

The `Strategy[P]` abstract class is the contract every strategy implements.
P is a Pydantic BaseModel describing the strategy's tunable parameters.

Contract:
  - Subclass declares PARAMS_MODEL: type[P]
  - Subclass implements on_bar(ctx: BarContext) -> None
  - Subclass MAY override on_init() -> None for one-time setup
  - Strategy.state is a free-form dict the strategy uses for persistent state
    between on_bar calls
  - Strategy.symbols is the list of canonical symbols the strategy operates on,
    passed at instantiation time
  - Strategy.params is the validated Pydantic params instance

The engine guarantees:
  - on_init() is called exactly once, before any on_bar()
  - on_bar() is called once per closed bar boundary in chronological order
  - The history accessible via ctx.bars() never includes future bars
  - Orders submitted via ctx.submit_*() are queued for fill simulation at the
    NEXT bar's open price (not the current bar — this prevents look-ahead bias)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass(frozen=True)
class Order:
    """A strategy-submitted order, awaiting fill simulation by the engine.

    Strategies don't construct Order directly; they call ctx.submit_market()
    or ctx.submit_limit(). The engine consumes these via ctx.collected_orders().
    """

    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None  # None for market orders; required for limit
    submitted_ts: datetime  # the bar close time at which the strategy decided
    client_order_id: str  # auto-generated; unique per strategy run

    def __post_init__(self) -> None:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit orders require limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("Market orders must not have limit_price")
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive: {self.quantity}")


P = TypeVar("P", bound=BaseModel)


class Strategy(Generic[P], ABC):
    """Abstract base class for all platform strategies.

    Subclasses define:
      PARAMS_MODEL: type[P] — Pydantic model describing tunable parameters
      on_bar(ctx)           — called on each closed bar boundary

    Subclasses may override:
      on_init()             — called once before the first bar
      name()                — defaults to class __name__
      description()         — defaults to class docstring
    """

    PARAMS_MODEL: ClassVar[type[BaseModel]]

    # Instance attributes (typed for IDE help)
    symbols: list[str]
    params: BaseModel
    state: dict[str, Any]

    def __init__(self, symbols: list[str], params: P) -> None:
        if not hasattr(self.__class__, "PARAMS_MODEL"):
            raise TypeError(
                f"{self.__class__.__name__} must declare PARAMS_MODEL class attribute"
            )
        if not isinstance(params, self.__class__.PARAMS_MODEL):
            raise TypeError(
                f"params must be an instance of {self.__class__.PARAMS_MODEL.__name__}, "
                f"got {type(params).__name__}"
            )
        if not symbols:
            raise ValueError("Strategy must be instantiated with at least one symbol")
        self.symbols = list(symbols)
        self.params = params
        self.state = {}

    # --- Lifecycle hooks ---

    def on_init(self) -> None:
        """Optional hook called once before the first bar."""
        return None

    @abstractmethod
    def on_bar(self, ctx: "BarContext") -> None:  # noqa: F821 (forward ref)
        """Required: process a closed-bar boundary, optionally submit orders.

        Called once per bar across all symbols. The context provides typed
        access to history, indicators, current positions, cash, and order
        submission.
        """
        ...

    # --- Discovery / metadata ---

    @classmethod
    def name(cls) -> str:
        """Stable identifier for this strategy. Defaults to class name."""
        return cls.__name__

    @classmethod
    def description(cls) -> str:
        """Human-readable description. Defaults to class docstring."""
        return (cls.__doc__ or "").strip()

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        """JSON schema of the params model, for UI form generation."""
        if not hasattr(cls, "PARAMS_MODEL"):
            return {}
        return cls.PARAMS_MODEL.model_json_schema()
