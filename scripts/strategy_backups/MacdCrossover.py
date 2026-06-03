"""MACD Crossover strategy.

Classic momentum-based trend following using MACD line and signal line crossovers.
"""
from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class MACDCrossoverParams(BaseModel):
    """Parameters for the MACD crossover strategy."""

    fast_period: int = Field(
        default=12, ge=2, le=100,
        description="Fast EMA period for MACD calculation, in bars.",
    )
    slow_period: int = Field(
        default=26, ge=3, le=200,
        description="Slow EMA period for MACD calculation. Must exceed fast_period.",
    )
    signal_period: int = Field(
        default=9, ge=2, le=50,
        description="EMA period for the MACD signal line, in bars.",
    )
    position_size: float = Field(
        default=0.01, gt=0,
        description="Quantity in base units bought per entry signal.",
    )

    @model_validator(mode="after")
    def _validate_periods(self) -> "MACDCrossoverParams":
        if self.slow_period <= self.fast_period:
            raise ValueError(
                f"slow_period ({self.slow_period}) must exceed fast_period "
                f"({self.fast_period})"
            )
        return self


class MACDCrossover(Strategy[MACDCrossoverParams]):
    """Long-flat MACD crossover on a single symbol."""

    PARAMS_MODEL = MACDCrossoverParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["prev_macd"] = None
        self.state["prev_signal"] = None

    def on_bar(self, ctx: BarContext) -> None:
        # Calculate MACD components
        fast_ema = ctx.ema(self.symbol, self.params.fast_period)
        slow_ema = ctx.ema(self.symbol, self.params.slow_period)

        if fast_ema is None or slow_ema is None:
            return

        # MACD line = fast EMA - slow EMA
        macd_line = fast_ema - slow_ema

        # We need to manually calculate the signal line (EMA of MACD)
        # For simplicity, we'll track previous MACD values and calculate
        # a simple approximation of the signal line
        prev_macd = self.state.get("prev_macd")
        prev_signal = self.state.get("prev_signal")

        if prev_macd is None:
            # First calculation - use MACD line as initial signal
            signal_line = macd_line
        else:
            # Calculate signal line as EMA of MACD
            alpha = Decimal(2) / (Decimal(self.params.signal_period) + 1)
            if prev_signal is None:
                signal_line = macd_line
            else:
                signal_line = alpha * macd_line + (1 - alpha) * prev_signal

        position = ctx.position(self.symbol)

        # Entry: MACD crosses above signal line
        if (prev_macd is not None and prev_signal is not None and
            prev_macd <= prev_signal and macd_line > signal_line and position == 0):
            ctx.submit_buy_market(self.symbol, self.params.position_size)

        # Exit: MACD crosses below signal line
        elif (prev_macd is not None and prev_signal is not None and
              prev_macd >= prev_signal and macd_line < signal_line and position > 0):
            ctx.submit_sell_market(self.symbol, position)

        # Update state for next bar
        self.state["prev_macd"] = macd_line
        self.state["prev_signal"] = signal_line