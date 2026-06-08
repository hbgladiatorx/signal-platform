"""Time-based buy and hold strategy.

Buys BTC every 2 minutes and holds for exactly 2 minutes before selling.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class TimedBuyHoldParams(BaseModel):
    """Parameters for the timed buy and hold strategy."""

    buy_interval: int = Field(
        default=2, ge=1, le=1440,
        description="Interval in minutes between buy signals.",
    )
    hold_duration: int = Field(
        default=2, ge=1, le=1440,
        description="Duration in minutes to hold positions before selling.",
    )
    position_size: float = Field(
        default=0.01, gt=0,
        description="Quantity in base units (e.g. BTC) bought per buy signal.",
    )


class TimedBuyHold(Strategy[TimedBuyHoldParams]):
    """Time-based buy and hold strategy on a single symbol."""

    PARAMS_MODEL = TimedBuyHoldParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["bar_count"] = 0
        self.state["last_buy_bar"] = None
        self.state["sell_at_bar"] = None

    def on_bar(self, ctx: BarContext) -> None:
        self.state["bar_count"] += 1
        current_bar = self.state["bar_count"]
        
        # Check if we need to sell (hold duration expired)
        if (self.state["sell_at_bar"] is not None and 
            current_bar >= self.state["sell_at_bar"]):
            position = ctx.position(self.symbol)
            if position > 0:
                ctx.submit_sell_market(self.symbol, position)
            self.state["sell_at_bar"] = None
        
        # Check if we need to buy (buy interval reached)
        last_buy = self.state["last_buy_bar"]
        if (last_buy is None or 
            current_bar >= last_buy + self.params.buy_interval):
            ctx.submit_buy_market(self.symbol, self.params.position_size)
            self.state["last_buy_bar"] = current_bar
            self.state["sell_at_bar"] = current_bar + self.params.hold_duration