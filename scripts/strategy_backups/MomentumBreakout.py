"""Momentum Breakout Strategy with Trend Filter.

Captures momentum-driven breakouts in uptrending markets with strict risk controls.
Designed for crypto assets with strong momentum characteristics.
"""
from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

from packages.strategy.base import Strategy
from packages.strategy.context import BarContext


class MomentumBreakoutParams(BaseModel):
    """Parameters for the momentum breakout strategy."""

    trend_fast_period: int = Field(
        default=50, ge=10, le=200,
        description="Lookback length of the fast EMA for trend filter, in bars.",
    )
    trend_slow_period: int = Field(
        default=200, ge=50, le=500,
        description="Lookback length of the slow EMA for trend filter. Must exceed trend_fast_period.",
    )
    breakout_period: int = Field(
        default=20, ge=5, le=100,
        description="Lookback period for finding the high to break above, in bars.",
    )
    volume_multiplier: float = Field(
        default=1.5, gt=1.0, le=5.0,
        description="Volume must be this multiple of recent average to confirm breakout.",
    )
    volume_avg_period: int = Field(
        default=20, ge=5, le=100,
        description="Period for calculating average volume, in bars.",
    )
    atr_period: int = Field(
        default=14, ge=5, le=50,
        description="Period for ATR calculation, in bars.",
    )
    stop_loss_atr_mult: float = Field(
        default=1.5, gt=0.5, le=5.0,
        description="Stop loss distance as multiple of ATR below entry price.",
    )
    take_profit_atr_mult: float = Field(
        default=3.0, gt=1.0, le=10.0,
        description="Take profit distance as multiple of ATR above entry price.",
    )
    position_size: float = Field(
        default=0.01, gt=0,
        description="Quantity in base units bought per entry signal.",
    )

    @model_validator(mode="after")
    def _validate_periods(self) -> "MomentumBreakoutParams":
        if self.trend_slow_period <= self.trend_fast_period:
            raise ValueError(
                f"trend_slow_period ({self.trend_slow_period}) must exceed "
                f"trend_fast_period ({self.trend_fast_period})"
            )
        if self.take_profit_atr_mult <= self.stop_loss_atr_mult:
            raise ValueError(
                f"take_profit_atr_mult ({self.take_profit_atr_mult}) should exceed "
                f"stop_loss_atr_mult ({self.stop_loss_atr_mult}) for positive risk/reward"
            )
        return self


class MomentumBreakout(Strategy[MomentumBreakoutParams]):
    """Momentum breakout strategy with trend filter and volatility confirmation."""

    PARAMS_MODEL = MomentumBreakoutParams

    def on_init(self) -> None:
        if len(self.symbols) != 1:
            raise ValueError(
                f"{self.__class__.__name__} supports exactly one symbol, "
                f"got {len(self.symbols)}: {self.symbols}"
            )
        self.symbol: str = self.symbols[0]
        self.state["entry_price"] = None
        self.state["stop_loss"] = None
        self.state["take_profit"] = None

    def on_bar(self, ctx: BarContext) -> None:
        # Get required indicators
        fast_ema = ctx.ema(self.symbol, self.params.trend_fast_period)
        slow_ema = ctx.ema(self.symbol, self.params.trend_slow_period)
        current_atr = ctx.atr(self.symbol, self.params.atr_period)
        current_close = ctx.close(self.symbol)
        current_volume = ctx.volume(self.symbol)
        
        # Need all indicators to proceed
        if (fast_ema is None or slow_ema is None or current_atr is None or 
            current_close is None or current_volume is None):
            return
            
        position = ctx.position(self.symbol)
        
        # Get historical data for breakout and volume analysis
        bars = ctx.bars(self.symbol)
        if len(bars) < max(self.params.breakout_period, self.params.volume_avg_period):
            return
            
        # Calculate breakout level (highest high of last N bars, excluding current)
        recent_highs = bars["high"].iloc[-self.params.breakout_period-1:-1]
        breakout_level = recent_highs.max()
        
        # Calculate average volume
        recent_volumes = bars["volume"].iloc[-self.params.volume_avg_period-1:-1]
        avg_volume = recent_volumes.mean()
        
        # Manage existing position
        if position > 0:
            entry_price = self.state.get("entry_price")
            stop_loss = self.state.get("stop_loss")
            take_profit = self.state.get("take_profit")
            
            if entry_price is not None and stop_loss is not None and take_profit is not None:
                # Check exit conditions
                if (current_close <= Decimal(str(stop_loss)) or 
                    current_close >= Decimal(str(take_profit)) or 
                    fast_ema <= slow_ema):  # Trend reversal
                    ctx.submit_sell_market(self.symbol, position)
                    # Clear state
                    self.state["entry_price"] = None
                    self.state["stop_loss"] = None
                    self.state["take_profit"] = None
            return
            
        # Entry logic: no position
        # Check trend filter: 50 EMA above 200 EMA
        if fast_ema <= slow_ema:
            return
            
        # Check breakout: current close above previous 20-candle high
        if current_close <= Decimal(str(breakout_level)):
            return
            
        # Check volume confirmation: unusually high volume
        if current_volume < avg_volume * self.params.volume_multiplier:
            return
            
        # Check volatility expansion: current ATR higher than recent average
        if len(bars) >= self.params.atr_period + 5:
            recent_atr_values = []
            for i in range(5):  # Check last 5 bars for ATR trend
                bar_idx = -(i+2)  # Skip current bar, go backwards
                if abs(bar_idx) <= len(bars):
                    # Calculate ATR for this historical point
                    hist_bars = bars.iloc[:bar_idx] if bar_idx < -1 else bars.iloc[:len(bars)-1]
                    if len(hist_bars) >= self.params.atr_period:
                        tr_values = []
                        for j in range(1, min(self.params.atr_period + 1, len(hist_bars))):
                            high = hist_bars["high"].iloc[-j]
                            low = hist_bars["low"].iloc[-j]
                            prev_close = hist_bars["close"].iloc[-j-1] if j < len(hist_bars)-1 else high
                            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                            tr_values.append(float(tr))
                        if tr_values:
                            recent_atr_values.append(sum(tr_values) / len(tr_values))
            
            if recent_atr_values and current_atr <= Decimal(str(sum(recent_atr_values) / len(recent_atr_values))):
                return  # No volatility expansion
        
        # All conditions met - enter trade
        ctx.submit_buy_market(self.symbol, self.params.position_size)
        
        # Set risk management levels
        entry_price = float(current_close)
        stop_loss = entry_price - (float(current_atr) * self.params.stop_loss_atr_mult)
        take_profit = entry_price + (float(current_atr) * self.params.take_profit_atr_mult)
        
        self.state["entry_price"] = entry_price
        self.state["stop_loss"] = stop_loss
        self.state["take_profit"] = take_profit