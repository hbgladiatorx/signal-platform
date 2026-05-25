"""Simple Moving Average crossover.

Classic long-flat trend-following baseline.

Logic:
  - Compute a fast SMA and a slow SMA of close prices.
  - When fast > slow AND we hold no position: buy `position_size` units.
  - When fast < slow AND we are long: sell the entire position (go flat).

Single symbol. No stop-loss. No position sizing logic beyond a fixed
quantity per entry. The point isn't to make money; the point is to
exercise the full framework end-to-end:
  - Params declared via Pydantic
  - History accessed via ctx.bars()
  - Indicator accessed via ctx.sma()
  - State persisted across bars via self.state
  - Orders submitted via ctx.submit_buy_market / submit_sell_market
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class SMACrossoverParams(BaseModel):
    """Parameters for the SMA crossover strategy."""

    model_config = {"extra": "forbid"}

    fast_period: int = Field(
        default=10,
        ge=2,
        le=200,
        description="Lookback length of the fast SMA, in bars.",
    )
    slow_period: int = Field(
        default=30,
        ge=3,
        le=500,
        description="Lookback length of the slow SMA. Must exceed fast_period.",
    )
    position_size: float = Field(
        default=0.01,
        gt=0,
        description="Quantity in base units (e.g. BTC) bought per entry signal.",
    )

    @model_validator(mode="after")
    def _validate_periods(self) -> "SMACrossoverParams":
        if self.slow_period <= self.fast_period:
            raise ValueError(
                f"slow_period ({self.slow_period}) must exceed fast_period "
                f"({self.fast_period})"
            )
        return self


class SMACrossover(Strategy[SMACrossoverParams]):
    """Long-flat SMA crossover on a single symbol."""

    PARAMS_MODEL = SMACrossoverParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.name()} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        # Track whether we believe we're long. Engine is the source of truth
        # for actual positions; this is just a hint for logging/diagnostics.
        self.state["signal"] = "flat"

    def on_bar(self, ctx: BarContext) -> None:
        fast = ctx.sma(self.symbol, self.params.fast_period)
        slow = ctx.sma(self.symbol, self.params.slow_period)

        # Not enough history yet
        if fast is None or slow is None:
            return

        position = ctx.position(self.symbol)

        if fast > slow and position == 0:
            ctx.submit_buy_market(self.symbol, self.params.position_size)
            self.state["signal"] = "long"
        elif fast < slow and position > 0:
            # Close the entire current position
            ctx.submit_sell_market(self.symbol, position)
            self.state["signal"] = "flat"
