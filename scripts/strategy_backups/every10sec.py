"""Time-based buy and hold strategy.

Buys a fixed amount every N bars and sells after holding for N bars.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class TimeBasedBuyHoldParams(BaseModel):
    """Parameters for the time-based buy and hold strategy."""

    buy_interval: int = Field(
        default=10, ge=1, le=1000,
        description="Number of bars between buy signals.",
    )
    hold_duration: int = Field(
        default=10, ge=1, le=1000,
        description="Number of bars to hold position before selling.",
    )
    position_size: float = Field(
        default=0.01, gt=0,
        description="Quantity in base units (e.g. BTC) bought per buy signal.",
    )


class TimeBasedBuyHold(Strategy[TimeBasedBuyHoldParams]):
    """Time-based buy and hold strategy on a single symbol."""

    PARAMS_MODEL = TimeBasedBuyHoldParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["bar_count"] = 0
        self.state["last_buy_bar"] = -1
        self.state["sell_bar"] = -1

    def on_bar(self, ctx: BarContext) -> None:
        current_bar = self.state["bar_count"]
        position = ctx.position(self.symbol)

        # Check if it's time to sell
        if (self.state["sell_bar"] != -1 and 
            current_bar >= self.state["sell_bar"] and 
            position > 0):
            ctx.submit_sell_market(self.symbol, position)
            self.state["sell_bar"] = -1

        # Check if it's time to buy
        if (current_bar - self.state["last_buy_bar"] >= self.params.buy_interval and
            position == 0):
            ctx.submit_buy_market(self.symbol, self.params.position_size)
            self.state["last_buy_bar"] = current_bar
            self.state["sell_bar"] = current_bar + self.params.hold_duration

        self.state["bar_count"] += 1