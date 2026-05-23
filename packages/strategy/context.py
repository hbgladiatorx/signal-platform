"""BarContext — the strategy's typed view of the market at a bar boundary.

Built fresh by the engine for each on_bar call. Provides:
  - History accessors: bars(), close(), open(), high(), low(), volume()
  - Indicator computation with per-context caching:
      sma(), ema(), rsi(), atr()
  - Position and cash inspection: position(), cash
  - Order submission: submit_market(), submit_limit(), and convenience helpers

The context is immutable from the engine's perspective after handing it to
the strategy, except for the orders collection — the strategy mutates that
by submitting orders.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from packages.strategy import indicators
from packages.strategy.base import Order, OrderSide, OrderType


# Numeric type accepted from strategy code for quantities/prices
Numeric = Decimal | float | int | str


def _to_decimal(v: Numeric) -> Decimal:
    """Coerce strategy-supplied numerics to Decimal safely (no float drift)."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


class BarContext:
    """Snapshot of market state at a bar boundary, plus order submission.

    Indicators are cached for the lifetime of the context: a strategy that
    queries ctx.sma(symbol, 20) twice in the same on_bar() call recomputes
    only once. Each new bar gets a new context.
    """

    def __init__(
        self,
        ts: datetime,
        symbols: list[str],
        history: dict[str, pd.DataFrame],
        positions: dict[str, Decimal],
        cash: Decimal,
    ) -> None:
        self.ts = ts
        self.symbols = list(symbols)
        self._history = history
        self._positions = positions
        self._cash = cash
        self._orders: list[Order] = []
        # Cache key: (symbol, indicator_name, *params) -> pd.Series
        self._cache: dict[tuple, pd.Series] = {}

    # ============================================================
    # History accessors
    # ============================================================
    def bars(self, symbol: str) -> pd.DataFrame:
        """Full history of bars for `symbol` up to and including the current bar.

        Returned DataFrame columns: open, high, low, close, volume.
        Index: bucket (DatetimeIndex, UTC).
        """
        df = self._history.get(symbol)
        if df is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return df

    def _last(self, symbol: str, column: str) -> Decimal | None:
        df = self._history.get(symbol)
        if df is None or df.empty or column not in df.columns:
            return None
        value = df[column].iloc[-1]
        if pd.isna(value):
            return None
        return _to_decimal(value)

    def close(self, symbol: str) -> Decimal | None:
        return self._last(symbol, "close")

    def open(self, symbol: str) -> Decimal | None:
        return self._last(symbol, "open")

    def high(self, symbol: str) -> Decimal | None:
        return self._last(symbol, "high")

    def low(self, symbol: str) -> Decimal | None:
        return self._last(symbol, "low")

    def volume(self, symbol: str) -> Decimal | None:
        return self._last(symbol, "volume")

    # ============================================================
    # Indicators (cached per (symbol, indicator_name, params))
    # ============================================================
    def _cached_indicator(
        self,
        symbol: str,
        name: str,
        period: int,
        compute: Any,
    ) -> Decimal | None:
        key = (symbol, name, period)
        if key in self._cache:
            series = self._cache[key]
        else:
            series = compute()
            if series is None:
                return None
            self._cache[key] = series

        if series.empty:
            return None
        last = series.iloc[-1]
        if pd.isna(last):
            return None
        return _to_decimal(last)

    def sma(self, symbol: str, period: int) -> Decimal | None:
        """SMA of close over `period` bars; None if not enough history."""

        def _compute() -> pd.Series | None:
            df = self._history.get(symbol)
            if df is None or len(df) < period:
                return None
            return indicators.sma(df["close"], period)

        return self._cached_indicator(symbol, "sma", period, _compute)

    def ema(self, symbol: str, period: int) -> Decimal | None:
        """EMA of close over `period` bars; None if not enough history."""

        def _compute() -> pd.Series | None:
            df = self._history.get(symbol)
            if df is None or len(df) < period:
                return None
            return indicators.ema(df["close"], period)

        return self._cached_indicator(symbol, "ema", period, _compute)

    def rsi(self, symbol: str, period: int = 14) -> Decimal | None:
        """Wilder-smoothed RSI over `period` bars; None if not enough history."""

        def _compute() -> pd.Series | None:
            df = self._history.get(symbol)
            # RSI needs period+1 bars to compute the first delta-based value
            if df is None or len(df) < period + 1:
                return None
            return indicators.rsi(df["close"], period)

        return self._cached_indicator(symbol, "rsi", period, _compute)

    def atr(self, symbol: str, period: int = 14) -> Decimal | None:
        """Average True Range over `period` bars; None if not enough history."""

        def _compute() -> pd.Series | None:
            df = self._history.get(symbol)
            if df is None or len(df) < period + 1:
                return None
            return indicators.atr(df["high"], df["low"], df["close"], period)

        return self._cached_indicator(symbol, "atr", period, _compute)

    # ============================================================
    # Position and cash
    # ============================================================
    def position(self, symbol: str) -> Decimal:
        """Current net position in `symbol`. Positive = long, negative = short, 0 = flat."""
        return self._positions.get(symbol, Decimal("0"))

    @property
    def cash(self) -> Decimal:
        """Cash balance available for new positions."""
        return self._cash

    # ============================================================
    # Order submission
    # ============================================================
    def _new_order_id(self) -> str:
        # 8 chars of UUID is plenty for uniqueness within a backtest run
        return uuid.uuid4().hex[:8]

    def submit_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
    ) -> str:
        """Queue a market order. Fills at next bar's open in the simulator."""
        order = Order(
            symbol=symbol,
            side=side,
            quantity=_to_decimal(quantity),
            order_type=OrderType.MARKET,
            limit_price=None,
            submitted_ts=self.ts,
            client_order_id=self._new_order_id(),
        )
        self._orders.append(order)
        return order.client_order_id

    def submit_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
        price: Numeric,
    ) -> str:
        """Queue a limit order. Fills in the simulator when price is crossed."""
        order = Order(
            symbol=symbol,
            side=side,
            quantity=_to_decimal(quantity),
            order_type=OrderType.LIMIT,
            limit_price=_to_decimal(price),
            submitted_ts=self.ts,
            client_order_id=self._new_order_id(),
        )
        self._orders.append(order)
        return order.client_order_id

    # ----- Convenience helpers -----

    def submit_buy_market(self, symbol: str, quantity: Numeric) -> str:
        return self.submit_market(symbol, OrderSide.BUY, quantity)

    def submit_sell_market(self, symbol: str, quantity: Numeric) -> str:
        return self.submit_market(symbol, OrderSide.SELL, quantity)

    def submit_buy_limit(self, symbol: str, quantity: Numeric, price: Numeric) -> str:
        return self.submit_limit(symbol, OrderSide.BUY, quantity, price)

    def submit_sell_limit(self, symbol: str, quantity: Numeric, price: Numeric) -> str:
        return self.submit_limit(symbol, OrderSide.SELL, quantity, price)

    # ============================================================
    # Engine interface
    # ============================================================
    def collected_orders(self) -> list[Order]:
        """Return the orders the strategy submitted in this on_bar() call."""
        return list(self._orders)
