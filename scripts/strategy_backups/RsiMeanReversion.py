"""RSI Mean Reversion strategy.

Buys when RSI drops to oversold levels and sells when RSI reaches overbought levels.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class RSIMeanReversionParams(BaseModel):
    """Parameters for the RSI mean reversion strategy."""

    rsi_period: int = Field(
        default=14, ge=2, le=100,
        description="Lookback period for RSI calculation, in bars.",
    )
    oversold_threshold: float = Field(
        default=30.0, ge=1.0, le=49.0,
        description="RSI level below which to trigger buy signals.",
    )
    overbought_threshold: float = Field(
        default=70.0, ge=51.0, le=99.0,
        description="RSI level above which to trigger sell signals.",
    )
    position_size: float = Field(
        default=0.01, gt=0,
        description="Quantity in base units (e.g. BTC) bought per entry signal.",
    )

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "RSIMeanReversionParams":
        if self.overbought_threshold <= self.oversold_threshold:
            raise ValueError(
                f"overbought_threshold ({self.overbought_threshold}) must exceed "
                f"oversold_threshold ({self.oversold_threshold})"
            )
        return self


class RSIMeanReversion(Strategy[RSIMeanReversionParams]):
    """Long-flat RSI mean reversion strategy on a single symbol."""

    PARAMS_MODEL = RSIMeanReversionParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]

    def on_bar(self, ctx: BarContext) -> None:
        rsi = ctx.rsi(self.symbol, self.params.rsi_period)

        if rsi is None:
            return

        position = ctx.position(self.symbol)

        # Buy when RSI is oversold and we're flat
        if rsi <= self.params.oversold_threshold and position == 0:
            ctx.submit_buy_market(self.symbol, self.params.position_size)
        
        # Sell when RSI is overbought and we have a position
        elif rsi >= self.params.overbought_threshold and position > 0:
            ctx.submit_sell_market(self.symbol, position)