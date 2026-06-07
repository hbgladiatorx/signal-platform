"""BarContext — the strategy's typed view of the market at a bar boundary.

Built fresh by the engine for each on_bar call. Provides:
  - History accessors: bars(), close(), open(), high(), low(), volume()
  - Indicator computation with per-context caching:
      sma(), ema(), rsi(), atr(), macd(), bollinger(), stoch(), vwap()
      crossed_above(), crossed_below()  (stateless MA-cross helpers)
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
from typing import Any, NamedTuple

import pandas as pd

from packages.strategy import indicators
from packages.strategy.base import Order, OrderSide, OrderType, SignalEvent
from packages.strategy.num import FlexDecimal, to_num


# Numeric type accepted from strategy code for quantities/prices
Numeric = Decimal | float | int | str


# ============================================================
# Multi-line indicator results (returned by ctx.macd/bollinger/stoch)
# ============================================================
class MACD(NamedTuple):
    """Current-bar MACD reading.

    ``macd`` and ``signal`` are comparable-scale lines (signal is the EMA of the
    macd line); ``hist`` = macd - signal. ``crossed_up``/``crossed_down`` are
    stateless crossover flags computed from the last two bars of ``hist`` — use
    them directly instead of tracking previous values yourself.
    """

    macd: FlexDecimal
    signal: FlexDecimal
    hist: FlexDecimal
    crossed_up: bool
    crossed_down: bool


class Bands(NamedTuple):
    """Current-bar Bollinger Bands. ``lower <= mid <= upper``."""

    upper: FlexDecimal
    mid: FlexDecimal
    lower: FlexDecimal


class Stochastic(NamedTuple):
    """Current-bar stochastic oscillator. ``k`` and ``d`` are in 0..100."""

    k: FlexDecimal
    d: FlexDecimal


def _to_decimal(v: Numeric) -> FlexDecimal:
    """Coerce strategy-supplied numerics to FlexDecimal (no float drift).

    Returns a FlexDecimal so any value handed back to strategy code interoperates
    with float/int in arithmetic (e.g. ``2.0 * ctx.atr(...)``) instead of raising
    TypeError, while remaining an exact Decimal for the money layer.
    """
    return to_num(v)


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
        # Multi-line indicators (macd, bollinger, stoch) cache a whole frame.
        # Cache key: (symbol, indicator_name, *params) -> pd.DataFrame
        self._frame_cache: dict[tuple, pd.DataFrame] = {}

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
    # Multi-line indicators (macd, bollinger, stochastic, vwap)
    # ============================================================
    def _cached_frame(
        self, key: tuple, compute: Any
    ) -> pd.DataFrame | None:
        if key in self._frame_cache:
            return self._frame_cache[key]
        frame = compute()
        if frame is None:
            return None
        self._frame_cache[key] = frame
        return frame

    def macd(
        self,
        symbol: str,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> MACD | None:
        """MACD reading for the current bar, or None if not enough history.

        The signal line is the EMA of the MACD line (comparable scale), NOT an
        SMA of price — so ``crossed_up``/``crossed_down`` are meaningful. Prefer
        those stateless flags over comparing ``macd``/``signal`` levels.
        """

        def _compute() -> pd.DataFrame | None:
            df = self._history.get(symbol)
            if df is None or len(df) < slow + signal:
                return None
            return indicators.macd(df["close"], fast, slow, signal)

        frame = self._cached_frame((symbol, "macd", fast, slow, signal), _compute)
        if frame is None or len(frame) < 2:
            return None
        last = frame.iloc[-1]
        prev = frame.iloc[-2]
        if pd.isna(last["macd"]) or pd.isna(last["signal"]):
            return None
        hist_now = last["hist"]
        hist_prev = prev["hist"]
        crossed_up = bool(not pd.isna(hist_prev) and hist_prev <= 0 < hist_now)
        crossed_down = bool(not pd.isna(hist_prev) and hist_prev >= 0 > hist_now)
        return MACD(
            macd=_to_decimal(last["macd"]),
            signal=_to_decimal(last["signal"]),
            hist=_to_decimal(hist_now),
            crossed_up=crossed_up,
            crossed_down=crossed_down,
        )

    def bollinger(
        self, symbol: str, period: int = 20, num_std: float = 2.0
    ) -> Bands | None:
        """Bollinger Bands for the current bar, or None if not enough history."""

        def _compute() -> pd.DataFrame | None:
            df = self._history.get(symbol)
            if df is None or len(df) < period:
                return None
            return indicators.bollinger(df["close"], period, num_std)

        frame = self._cached_frame(
            (symbol, "bollinger", period, num_std), _compute
        )
        if frame is None or frame.empty:
            return None
        last = frame.iloc[-1]
        if pd.isna(last["mid"]):
            return None
        return Bands(
            upper=_to_decimal(last["upper"]),
            mid=_to_decimal(last["mid"]),
            lower=_to_decimal(last["lower"]),
        )

    def stoch(
        self, symbol: str, k_period: int = 14, d_period: int = 3
    ) -> Stochastic | None:
        """Stochastic %K/%D for the current bar, or None if not enough history."""

        def _compute() -> pd.DataFrame | None:
            df = self._history.get(symbol)
            if df is None or len(df) < k_period + d_period:
                return None
            return indicators.stochastic(
                df["high"], df["low"], df["close"], k_period, d_period
            )

        frame = self._cached_frame(
            (symbol, "stoch", k_period, d_period), _compute
        )
        if frame is None or frame.empty:
            return None
        last = frame.iloc[-1]
        if pd.isna(last["k"]) or pd.isna(last["d"]):
            return None
        return Stochastic(k=_to_decimal(last["k"]), d=_to_decimal(last["d"]))

    def vwap(self, symbol: str, period: int | None = None) -> Decimal | None:
        """Volume-weighted average price for the current bar.

        Rolling over ``period`` bars when given, else cumulative from the start
        of available history. None if there isn't enough history/volume.
        """

        def _compute() -> pd.Series | None:
            df = self._history.get(symbol)
            if df is None or df.empty:
                return None
            if period is not None and len(df) < period:
                return None
            return indicators.vwap(
                df["high"], df["low"], df["close"], df["volume"], period
            )

        key = (symbol, "vwap", period)
        if key in self._cache:
            series = self._cache[key]
        else:
            series = _compute()
            if series is None:
                return None
            self._cache[key] = series
        if series.empty:
            return None
        last = series.iloc[-1]
        if pd.isna(last):
            return None
        return _to_decimal(last)

    # ============================================================
    # Crossover helpers (stateless — read the last two bars)
    # ============================================================
    def _cross(
        self, symbol: str, fast_period: int, slow_period: int, kind: str, above: bool
    ) -> bool | None:
        fn = {"sma": indicators.sma, "ema": indicators.ema}.get(kind)
        if fn is None:
            raise ValueError(f"crossed_* kind must be 'sma' or 'ema', got {kind!r}")
        df = self._history.get(symbol)
        need = max(fast_period, slow_period) + 1
        if df is None or len(df) < need:
            return None
        fast = fn(df["close"], fast_period)
        slow = fn(df["close"], slow_period)
        if len(fast) < 2 or len(slow) < 2:
            return None
        f_prev, f_now = fast.iloc[-2], fast.iloc[-1]
        s_prev, s_now = slow.iloc[-2], slow.iloc[-1]
        if any(pd.isna(x) for x in (f_prev, f_now, s_prev, s_now)):
            return None
        if above:
            return bool(f_prev <= s_prev and f_now > s_now)
        return bool(f_prev >= s_prev and f_now < s_now)

    def crossed_above(
        self, symbol: str, fast_period: int, slow_period: int, kind: str = "sma"
    ) -> bool | None:
        """True if the fast MA crossed ABOVE the slow MA on this bar.

        Stateless: compares the last two bars of each MA. ``kind`` is "sma" or
        "ema". None until there is enough history.
        """
        return self._cross(symbol, fast_period, slow_period, kind, above=True)

    def crossed_below(
        self, symbol: str, fast_period: int, slow_period: int, kind: str = "sma"
    ) -> bool | None:
        """True if the fast MA crossed BELOW the slow MA on this bar.

        Stateless: compares the last two bars of each MA. ``kind`` is "sma" or
        "ema". None until there is enough history.
        """
        return self._cross(symbol, fast_period, slow_period, kind, above=False)

    # ============================================================
    # Position and cash
    # ============================================================
    def position(self, symbol: str) -> FlexDecimal:
        """Current net position in `symbol`. Positive = long, negative = short, 0 = flat."""
        return to_num(self._positions.get(symbol, Decimal("0")))

    @property
    def cash(self) -> FlexDecimal:
        """Cash balance available for new positions."""
        return to_num(self._cash)

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

    # ----- Stop / trailing-stop orders (engine-triggered, no polling) -----

    def submit_stop(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
        stop_price: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        """Queue a stop (stop-market) order. The engine triggers it intrabar
        when price crosses `stop_price` and fills like a market order."""
        order = Order(
            symbol=symbol,
            side=side,
            quantity=_to_decimal(quantity),
            order_type=OrderType.STOP,
            limit_price=None,
            submitted_ts=self.ts,
            client_order_id=self._new_order_id(),
            expires_at_bar_count=self._compute_expiry(expires_after_bars),
            stop_price=_to_decimal(stop_price),
            tags=self._tags_for(symbol),
        )
        self._orders.append(order)
        return order.client_order_id

    def submit_trailing_stop(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Numeric,
        trail_percent: Numeric,
        expires_after_bars: int | None = None,
    ) -> str:
        """Queue a trailing-stop order whose trigger ratchets with the position's
        favourable move by `trail_percent` (e.g. 5 = 5%)."""
        order = Order(
            symbol=symbol,
            side=side,
            quantity=_to_decimal(quantity),
            order_type=OrderType.TRAILING_STOP,
            limit_price=None,
            submitted_ts=self.ts,
            client_order_id=self._new_order_id(),
            expires_at_bar_count=self._compute_expiry(expires_after_bars),
            trail_percent=_to_decimal(trail_percent),
            tags=self._tags_for(symbol),
        )
        self._orders.append(order)
        return order.client_order_id

    def submit_stop_loss(
        self,
        symbol: str,
        stop_price: Numeric,
        quantity: Numeric | None = None,
    ) -> str:
        """Protective stop for the CURRENT open position in `symbol`.

        Picks the correct side automatically: a long is protected by a SELL
        stop, a short by a BUY stop. Defaults the quantity to the full position.
        Raises if the position is flat.
        """
        pos = self.position(symbol)
        if pos > 0:
            side = OrderSide.SELL
        elif pos < 0:
            side = OrderSide.BUY
        else:
            raise ValueError(f"submit_stop_loss: no open position in {symbol}")
        qty = abs(pos) if quantity is None else _to_decimal(quantity)
        return self.submit_stop(symbol, side, qty, stop_price)

    def submit_take_profit(
        self,
        symbol: str,
        limit_price: Numeric,
        quantity: Numeric | None = None,
    ) -> str:
        """Protective take-profit (resting limit) for the CURRENT position.

        A long takes profit with a SELL limit above; a short with a BUY limit
        below. Defaults the quantity to the full position. Raises if flat.
        """
        pos = self.position(symbol)
        if pos > 0:
            side = OrderSide.SELL
        elif pos < 0:
            side = OrderSide.BUY
        else:
            raise ValueError(f"submit_take_profit: no open position in {symbol}")
        qty = abs(pos) if quantity is None else _to_decimal(quantity)
        return self.submit_limit(symbol, side, qty, limit_price)

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
