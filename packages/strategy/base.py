"""Strategy framework — base class and core types.

The `Strategy[P]` abstract class is the contract every strategy implements.
P is a Pydantic BaseModel describing the strategy's tunable parameters.

Contract:
  - Subclass declares PARAMS_MODEL: type[P]
  - Subclass implements on_bar(ctx: BarContext) -> None
  - Subclass MAY override on_init() -> None for one-time setup
  - Subclass MAY override on_order_rejected, on_order_cancelled,
    on_order_expired to react to order lifecycle events. These default
    to no-ops so strategies that don't care can ignore them.
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
  - Order lifecycle callbacks fire BEFORE on_bar() for the bar in which the
    event was determined. So if an order expires going into bar N, the
    strategy sees on_order_expired() before its on_bar(N) is invoked.
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

    `expires_at_bar_count` is the engine's bar index AT WHICH the order
    expires (i.e., before that bar's fill phase). None means GTC.
    """

    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None  # None for market orders; required for limit
    submitted_ts: datetime  # the bar close time at which the strategy decided
    client_order_id: str  # auto-generated; unique per strategy run
    expires_at_bar_count: int | None = None  # None = GTC (no expiry)
    # Attribution tags: the names of the signals the strategy emitted (via
    # ctx.signal(...)) in the same on_bar() before submitting this order. These
    # are the causal link used by attribution analytics to answer "which signal
    # / filter drove this trade". Empty for strategies that emit no signals.
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit orders require limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("Market orders must not have limit_price")
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive: {self.quantity}")


@dataclass(frozen=True)
class SignalEvent:
    """A discrete signal or filter outcome a strategy emitted during on_bar().

    Strategies call ctx.signal(name, passed=..., value=..., symbol=...) to
    record that a condition fired (e.g. "rsi_oversold") or that a filter
    blocked an action (passed=False, e.g. "atr_filter" rejecting an entry).

    These events are the raw material for attribution analytics: how often a
    signal fired, what fraction passed its filters, and — when an order was
    submitted in the same bar — how the resulting trades performed.

    `value` carries an optional numeric reading (e.g. the RSI value) so the
    same log doubles as a feature/label store for the later ML/DRL phase.

    Lives in the strategy package (not backtest) because it is part of the
    strategy-facing contract, exactly like Order — both backtest and live
    paths emit and consume it without depending on the backtest package.
    """

    ts: datetime
    bar_count: int
    name: str
    passed: bool = True
    symbol: str | None = None
    value: Decimal | None = None
    meta: dict[str, Any] = field(default_factory=dict)


P = TypeVar("P", bound=BaseModel)


class Strategy(Generic[P], ABC):
    """Abstract base class for all platform strategies.

    Subclasses define:
      PARAMS_MODEL: type[P] — Pydantic model describing tunable parameters
      on_bar(ctx)           — called on each closed bar boundary

    Subclasses may override:
      on_init()             — called once before the first bar
      on_order_rejected()   — engine couldn't fill (insufficient cash/position)
      on_order_cancelled()  — strategy-requested cancellation took effect
      on_order_expired()    — order reached expires_at_bar_count without filling
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
        access to history, indicators, current positions, cash, pending
        orders, and order submission.
        """
        ...

    # --- Order lifecycle hooks (defaults are no-ops) ---

    def on_order_rejected(self, order: Order, reason: str) -> None:
        """Optional: react when the engine declined to fill an order.

        Reasons include insufficient cash for a buy, or attempting to sell
        more than the current position. Default is a no-op; override to
        log, retry-with-smaller-size, or update strategy state.
        """
        return None

    def on_order_cancelled(self, order: Order) -> None:
        """Optional: react when a strategy-requested cancellation completes.

        Fires when an order the strategy cancelled via ctx.cancel_order()
        is removed from the pending queue by the engine. Default is a no-op.
        """
        return None

    def on_order_expired(self, order: Order) -> None:
        """Optional: react when an order expires without filling.

        Fires when an order's expires_at_bar_count is reached before it
        fills. Default is a no-op.
        """
        return None

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
