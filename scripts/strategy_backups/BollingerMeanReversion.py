"""Mean reversion strategy using Bollinger Bands.

Trades deviations from statistical normal range, entering long when price
drops below lower band and exiting when returning toward mean or hitting stops.
"""
from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class BollingerMeanReversionParams(BaseModel):
    """Parameters for the Bollinger Band mean reversion strategy."""

    period: int = Field(
        default=20, ge=5, le=100,
        description="Lookback period for moving average and standard deviation calculation.",
    )
    std_dev_multiplier: float = Field(
        default=2.0, ge=0.5, le=5.0,
        description="Number of standard deviations for band calculation.",
    )
    position_size: float = Field(
        default=0.01, gt=0, le=1.0,
        description="Base position size in units. Will be scaled by volatility.",
    )
    atr_period: int = Field(
        default=14, ge=5, le=50,
        description="Period for ATR calculation used in position sizing and stops.",
    )
    stop_loss_atr_multiple: float = Field(
        default=2.0, ge=0.5, le=10.0,
        description="Stop loss distance as multiple of ATR.",
    )
    min_volatility_filter: float = Field(
        default=0.02, ge=0.001, le=0.1,
        description="Minimum volatility (price std dev / price) required to trade.",
    )
    max_volatility_filter: float = Field(
        default=0.15, ge=0.05, le=1.0,
        description="Maximum volatility allowed to trade. Must exceed min_volatility_filter.",
    )

    @model_validator(mode="after")
    def _validate_volatility_filters(self) -> "BollingerMeanReversionParams":
        if self.max_volatility_filter <= self.min_volatility_filter:
            raise ValueError(
                f"max_volatility_filter ({self.max_volatility_filter}) must exceed "
                f"min_volatility_filter ({self.min_volatility_filter})"
            )
        return self


class BollingerMeanReversion(Strategy[BollingerMeanReversionParams]):
    """Mean reversion strategy using Bollinger Bands with volatility filtering."""

    PARAMS_MODEL = BollingerMeanReversionParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["entry_price"] = None
        self.state["stop_price"] = None

    def on_bar(self, ctx: BarContext) -> None:
        # Get required indicators
        sma = ctx.sma(self.symbol, self.params.period)
        close = ctx.close(self.symbol)
        atr = ctx.atr(self.symbol, self.params.atr_period)
        
        if sma is None or close is None or atr is None:
            return

        # Calculate Bollinger Bands using historical data
        bars = ctx.bars(self.symbol)
        if len(bars) < self.params.period:
            return
            
        # Get recent closes for standard deviation calculation
        recent_closes = bars["close"].tail(self.params.period)
        std_dev = float(recent_closes.std())
        
        # Calculate bands
        upper_band = sma + Decimal(str(self.params.std_dev_multiplier * std_dev))
        lower_band = sma - Decimal(str(self.params.std_dev_multiplier * std_dev))
        
        # Volatility filter
        volatility = std_dev / float(sma)
        if volatility < self.params.min_volatility_filter or volatility > self.params.max_volatility_filter:
            return
            
        position = ctx.position(self.symbol)
        
        # Entry logic: buy when price drops below lower band
        if position == 0 and close < lower_band:
            # Scale position size by inverse volatility (lower vol = larger size)
            vol_adjusted_size = self.params.position_size / max(volatility, 0.01)
            vol_adjusted_size = min(vol_adjusted_size, self.params.position_size * 2)  # Cap at 2x base size
            
            ctx.submit_buy_market(self.symbol, vol_adjusted_size)
            self.state["entry_price"] = float(close)
            self.state["stop_price"] = float(close - atr * Decimal(str(self.params.stop_loss_atr_multiple)))
            
        # Exit logic: close position if price reverts to mean or hits stop
        elif position > 0:
            entry_price = self.state.get("entry_price")
            stop_price = self.state.get("stop_price")
            
            # Exit conditions
            should_exit = False
            
            # Mean reversion exit: price returned above SMA
            if close >= sma:
                should_exit = True
                
            # Stop loss exit
            if stop_price and close <= Decimal(str(stop_price)):
                should_exit = True
                
            # Profit taking: price moved significantly above upper band
            if close > upper_band * Decimal("1.01"):  # 1% above upper band
                should_exit = True
                
            if should_exit:
                ctx.submit_sell_market(self.symbol, position)
                self.state["entry_price"] = None
                self.state["stop_price"] = None