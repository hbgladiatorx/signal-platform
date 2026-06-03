"""BarContext — the strategy's typed view of the market at a bar boundary.

Built fresh by the engine for each on_bar call. Provides:
  - History accessors: bars(), close(), open(), high(), low(), volume()
  - Indicator computation with per-context caching:
      sma(), ema(), rsi(), atr()
  - Position and cash inspection: position(), cash
  - Order submission: submit_market(), submit_limit(), and convenience helpers
  - Order management: cancel_order(), pending_orders()

The context is immutable from the engine's perspective after handing it to
the strategy, except for the orders/cancellations collections — the strategy
mutates those by submitting orders and requesting cancellations.

Cancellations and new orders are queued during on_bar(); the engine processes
them at the start of the NEXT bar's fill phase. This keeps the engine's
processing order deterministic and prevents same-bar cancel-after-fill races.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from packages.strategy import indicators
from packages.strategy.base import Order, OrderSide, OrderType, SignalEvent


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
        pending_orders: list[Order] | None = None,
        bar_count: int = 0,
        order_id_factory: Callable[[], str] | None = None,
        option_chain: list[dict[str, Any]] | None = None,
    ) -> None:
        self.ts = ts
        self.symbols = list(symbols)
        # Read-only snapshot of option contracts available this bar (each a dict
        # with keys: symbol, underlying, right, strike, expiry, multiplier).
        self._option_chain: list[dict[str, Any]] = list(option_chain or [])
        self.bar_count = bar_count  # engine-maintained bar index, 0-based
        # Live trading injects a factory that yields deterministic, namespaced
        # ids (pt_{session}_{bar}_{seq}) so re-running a bar produces the same
        # ids (broker-side dedup) and strategies can still cancel by the id
        # submit_*() returned. Backtest leaves this None → random ids.
        self._order_id_factory = order_id_factory
        self._history = history
        self._positions = positions
        self._cash = cash
        # Snapshot of orders currently pending fill in the engine
        self._pending_orders: list[Order] = (
            list(pending_orders) if pending_orders else []
        )
        # New orders the strategy submits this bar
        self._orders: list[Order] = []
        # Cancellation requests the strategy makes this bar
        self._cancellation_requests: set[str] = set()
        # Signal/filter events the strategy emits this bar (attribution).
        self._signals: list[SignalEvent] = []
        # PASSED signals emitted so far this bar, as (name, symbol) pairs.
        # When an order is submitted, it is tagged with every active signal
        # whose symbol is None (global) or matches the order's symbol — so a
        # per-symbol signal only attributes that symbol's orders, while a
        # global signal attributes all of them. Forms the causal
        # "this signal drove this trade" link. Ordered; de-duped on submit.
        self._active_signals: list[tuple[str, str | None]] = []
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
    # Signals / filters (attribution — the "why")
    # ============================================================
    def signal(
        self,
        name: str,
        *,
        passed: bool = True,
        value: Numeric | None = None,
        symbol: str | None = None,
        **meta: Any,
    ) -> bool:
        """Record that a signal fired or a filter was evaluated this bar.

        This is the hook that lets a backtest explain *why* it traded. Emit a
        signal right before you act on it, then submit your order; the order
        (and the resulting fills and round trip) are tagged with this signal's
        name, so attribution analytics can report the P&L, win rate, and trade
        count attributable to each signal/filter.

        Examples
        --------
        Tag an entry with the condition that triggered it::

            rsi = ctx.rsi(sym)
            if rsi is not None and rsi < self.params.oversold:
                ctx.signal("rsi_oversold", value=rsi, symbol=sym)
                ctx.submit_buy_market(sym, qty)   # tagged "rsi_oversold"

        Record a filter that *blocked* an entry (passed=False) so you can later
        see how much a filter is helping or hurting::

            if ctx.atr(sym) is not None and ctx.atr(sym) > self.params.atr_max:
                ctx.signal("atr_too_high", passed=False, value=ctx.atr(sym))
                return  # no order — this signal is NOT attached as a tag

        Only signals with ``passed=True`` become order tags; a ``passed=False``
        event is still logged (for filter-frequency analysis) but does not
        attribute trades. Returns ``passed`` so it can be used inline:
        ``if ctx.signal("cooldown", passed=not in_cooldown): ...``.
        """
        self._signals.append(
            SignalEvent(
                ts=self.ts,
                bar_count=self.bar_count,
                name=name,
                passed=passed,
                symbol=symbol,
                value=_to_decimal(value) if value is not None else None,
                meta=dict(meta),
            )
        )
        if passed and (name, symbol) not in self._active_signals:
            self._active_signals.append((name, symbol))
        return passed

    def _tags_for(self, symbol: str) -> tuple[str, ...]:
        """Active passed-signal names applicable to an order on `symbol`:
        global signals (symbol=None) plus those emitted for this symbol."""
        tags: list[str] = []
        for name, sig_symbol in self._active_signals:
            if (sig_symbol is None or sig_symbol == symbol) and name not in tags:
                tags.append(name)
        return tuple(tags)

    # ============================================================
    # Order submission
    # ============================================================
    def _new_order_id(self) -> str:
        if self._order_id_factory is not None:
            return self._order_id_factory()
        # 8 chars of UUID is plenty for uniqueness within a backtest run
        return uuid.uuid4().hex[:8]

    def _compute_expiry(self, expires_after_bars: int | None) -> int | None:
        """Translate strategy-provided 'expires after N bars' into the absolute
        engine bar index at which the order expires."""
        if expires_after_bars is None:
            return None
        if expires_after_bars <= 0:
            raise ValueError(
                f"expires_after_bars must be positive, got {expires_after_bars}"
            )
        return self.bar_count + expires_after_bars

    def submit_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
        expires_after_bars: int | None = None,
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
            expires_at_bar_count=self._compute_expiry(expires_after_bars),
            tags=self._tags_for(symbol),
        )
        self._orders.append(order)
        return order.client_order_id

    def submit_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
        price: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        """Queue a limit order. Fills in the simulator when price is crossed.

        If `expires_after_bars` is provided, the order expires after that many
        bars without filling and on_order_expired() is called. Without an
        expiry, the order is GTC and persists until filled or cancelled.
        """
        order = Order(
            symbol=symbol,
            side=side,
            quantity=_to_decimal(quantity),
            order_type=OrderType.LIMIT,
            limit_price=_to_decimal(price),
            submitted_ts=self.ts,
            client_order_id=self._new_order_id(),
            expires_at_bar_count=self._compute_expiry(expires_after_bars),
            tags=self._tags_for(symbol),
        )
        self._orders.append(order)
        return order.client_order_id

    # ----- Options -----

    def option_chain(
        self,
        underlying: str | None = None,
        *,
        right: str | None = None,
        expiry: str | None = None,
    ) -> list[dict[str, Any]]:
        """Available option contracts this bar, optionally filtered by underlying
        canonical symbol, right ('C'/'P'), and/or expiry (YYYY-MM-DD)."""
        out = self._option_chain
        if underlying is not None:
            out = [c for c in out if c.get("underlying") == underlying]
        if right is not None:
            out = [c for c in out if (c.get("right") or "").upper() == right.upper()]
        if expiry is not None:
            out = [c for c in out if str(c.get("expiry")) == expiry]
        return list(out)

    def option_quote(self, occ_symbol: str) -> Decimal | None:
        """Latest known price (last close) for an option contract symbol."""
        return self.close(occ_symbol)

    def submit_option_market(
        self,
        occ_symbol: str,
        side: OrderSide,
        contracts: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        """Submit a single-leg option market order (quantity is # of contracts)."""
        return self.submit_market(occ_symbol, side, contracts, expires_after_bars)

    def submit_option_limit(
        self,
        occ_symbol: str,
        side: OrderSide,
        contracts: Numeric,
        price: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        """Submit a single-leg option limit order (quantity is # of contracts)."""
        return self.submit_limit(occ_symbol, side, contracts, price, expires_after_bars)

    # ----- Convenience helpers -----

    def submit_buy_market(
        self,
        symbol: str,
        quantity: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        return self.submit_market(
            symbol, OrderSide.BUY, quantity, expires_after_bars
        )

    def submit_sell_market(
        self,
        symbol: str,
        quantity: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        return self.submit_market(
            symbol, OrderSide.SELL, quantity, expires_after_bars
        )

    def submit_buy_limit(
        self,
        symbol: str,
        quantity: Numeric,
        price: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        return self.submit_limit(
            symbol, OrderSide.BUY, quantity, price, expires_after_bars
        )

    def submit_sell_limit(
        self,
        symbol: str,
        quantity: Numeric,
        price: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        return self.submit_limit(
            symbol, OrderSide.SELL, quantity, price, expires_after_bars
        )

    # ============================================================
    # Order management
    # ============================================================
    def cancel_order(self, client_order_id: str) -> bool:
        """Request cancellation of a pending order.

        Returns True if the id matches an order currently pending or
        newly submitted in this bar; False otherwise (no-op).

        Cancellation takes effect at the START of the next bar, BEFORE
        the engine attempts to fill orders. So an order cancelled in
        bar N's on_bar will not be filled in bar N+1's fill phase.
        """
        self._cancellation_requests.add(client_order_id)
        in_pending = any(
            o.client_order_id == client_order_id for o in self._pending_orders
        )
        in_new = any(
            o.client_order_id == client_order_id for o in self._orders
        )
        return in_pending or in_new

    def pending_orders(self) -> list[Order]:
        """Snapshot of orders currently pending in the engine.

        Does NOT include orders the strategy submitted this bar (those
        are in flight but not yet in the engine's queue). Use this to
        introspect what's outstanding before submitting more.
        """
        return list(self._pending_orders)

    # ============================================================
    # Engine interface
    # ============================================================
    def collected_orders(self) -> list[Order]:
        """Return the orders the strategy submitted in this on_bar() call."""
        return list(self._orders)

    def collected_cancellations(self) -> set[str]:
        """Return the cancellation requests collected this on_bar() call."""
        return set(self._cancellation_requests)

    def collected_signals(self) -> list[SignalEvent]:
        """Return the signal/filter events the strategy emitted this bar."""
        return list(self._signals)
