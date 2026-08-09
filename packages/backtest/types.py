"""Backtest result types — pure data structures.

These are the I/O of run_backtest(). The engine populates them; downstream
consumers (analytics in Step 21, persistence in Step 22, UI in Step 26)
read from them.

All monetary values are Decimal for precision. Floats are used only for
serialization to JSON or pandas operations and are explicitly converted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from packages.strategy.base import Order, OrderSide, OrderType, SignalEvent

# Re-exported so downstream code can import SignalEvent from the backtest types
# module alongside the other result types, even though it is defined in the
# strategy package (it is part of the strategy-facing contract).
__all__ = [
    "InstrumentMeta",
    "BacktestConfig",
    "Fill",
    "Position",
    "EquityPoint",
    "BacktestResult",
    "SignalEvent",
]


# ============================================================
# Instrument metadata (drives multiplier / option settlement)
# ============================================================
@dataclass(frozen=True)
class InstrumentMeta:
    """Per-symbol facts the engine needs for non-equity/crypto handling.

    Defaults describe a plain 1x instrument (equity/crypto), so when no meta is
    supplied the engine behaves exactly as before. Options set multiplier=100
    and provide expiry/right/strike (and the underlying canonical symbol when
    available) so positions can be settled at expiry.
    """

    multiplier: Decimal = Decimal(1)
    asset_class: str = "equity"
    expiry: date | None = None
    right: str | None = None  # 'C' or 'P'
    strike: Decimal | None = None
    underlying: str | None = None  # canonical symbol of the underlier


# ============================================================
# Configuration
# ============================================================
@dataclass(frozen=True)
class BacktestConfig:
    """Knobs that control the simulator's realism.

    Defaults model a small retail crypto account on Binance.US:
      - 10 bps (0.10%) fee per fill (Binance.US taker after volume tiers)
      - 5 bps (0.05%) slippage on market orders
      - $10,000 starting cash
      - No volume cap (full fills regardless of bar volume)

    Setting `max_pct_of_volume` to e.g. 0.05 caps any single fill at 5%
    of the bar's traded volume. Remainders are automatically requeued
    for the next bar with the same client_order_id.
    """

    starting_cash: Decimal = Decimal("10000")
    fee_rate_bps: int = 10
    slippage_bps: int = 5
    max_pct_of_volume: Decimal | None = None
    # Per-contract commission for options (Alpaca-style ~$0.65/contract).
    option_fee_per_contract: Decimal = Decimal("0.65")
    # Optional per-symbol overrides. When both are None the engine is identical
    # to its pre-options behavior (multiplier 1, bps fees), so crypto/equity
    # backtests are unaffected.
    contract_multipliers: dict[str, Decimal] | None = None
    instrument_meta: dict[str, "InstrumentMeta"] | None = None
    # --- Shorting / margin ---
    # allow_short=False reverts to the original long-only behavior (a fill that
    # would make a position negative is rejected). margin_rate is the fraction
    # of gross exposure that post-fill equity must cover when a fill INCREASES
    # exposure: 1.0 = fully collateralized (no leverage), 0.5 = 2:1, etc.
    allow_short: bool = True
    margin_rate: Decimal = Decimal(1)
    # --- Realistic maker (limit) fill model ---
    # All default to a no-op: with maker_fee_bps=None and the two margins at 0,
    # try_fill_limit_order behaves byte-for-byte as before (optimistic touch-fill).
    #   maker_fee_bps          : fee on limit fills (None -> fall back to fee_rate_bps).
    #   fill_through_margin_bps : a limit fills only if the bar trades PAST it by this
    #                             many bps (queue-position / non-fill proxy), not on a
    #                             mere touch.
    #   adverse_selection_bps  : book maker fills this many bps WORSE than the limit
    #                             (you tend to get filled right before price moves
    #                             against you).
    maker_fee_bps: int | None = None
    fill_through_margin_bps: int = 0
    adverse_selection_bps: int = 0

    @property
    def fee_rate(self) -> Decimal:
        """Fee as a Decimal fraction (e.g. 0.001 for 10 bps)."""
        return Decimal(self.fee_rate_bps) / Decimal(10_000)

    @property
    def slippage(self) -> Decimal:
        """Slippage as a Decimal fraction."""
        return Decimal(self.slippage_bps) / Decimal(10_000)

    def multiplier_for(self, symbol: str) -> Decimal:
        """Contract multiplier for a symbol (1 for equity/crypto, 100 options)."""
        if self.contract_multipliers and symbol in self.contract_multipliers:
            return self.contract_multipliers[symbol]
        if self.instrument_meta and symbol in self.instrument_meta:
            return self.instrument_meta[symbol].multiplier
        return Decimal(1)

    def meta_for(self, symbol: str) -> "InstrumentMeta | None":
        if self.instrument_meta:
            return self.instrument_meta.get(symbol)
        return None

    def fee_for(self, symbol: str, fill_price: Decimal, quantity: Decimal) -> Decimal:
        """Fee for a fill: per-contract for options, bps of notional otherwise."""
        meta = self.meta_for(symbol)
        if meta is not None and meta.asset_class == "option":
            return self.option_fee_per_contract * quantity
        return fill_price * quantity * self.fee_rate

    def maker_fee_for(self, symbol: str, fill_price: Decimal, quantity: Decimal) -> Decimal:
        """Fee for a maker (limit) fill. Uses maker_fee_bps when set, else fee_rate."""
        meta = self.meta_for(symbol)
        if meta is not None and meta.asset_class == "option":
            return self.option_fee_per_contract * quantity
        rate = (Decimal(self.maker_fee_bps) / Decimal(10_000)
                if self.maker_fee_bps is not None else self.fee_rate)
        return fill_price * quantity * rate

    @property
    def through_margin(self) -> Decimal:
        """Through-fill margin as a Decimal fraction."""
        return Decimal(self.fill_through_margin_bps) / Decimal(10_000)

    @property
    def adverse_selection(self) -> Decimal:
        """Adverse-selection penalty as a Decimal fraction."""
        return Decimal(self.adverse_selection_bps) / Decimal(10_000)


# ============================================================
# Per-trade records
# ============================================================
@dataclass(frozen=True)
class Fill:
    """A filled order in the simulator.

    `price` is the actual fill price including slippage. `fee` is the
    absolute amount paid in fees on this fill (in quote currency).
    `filled_ts` is the timestamp of the BAR at which the fill occurred,
    which is one bar after `order_submitted_ts` for market orders.

    `is_partial` indicates whether this fill is a partial — i.e. the
    engine capped the fill quantity (typically because of the volume
    cap), and a remainder order with the same client_order_id is now
    queued for further fills on subsequent bars.
    """

    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_ts: datetime
    order_submitted_ts: datetime
    is_partial: bool = False
    # Attribution tags copied from the originating Order (the signals active
    # when the strategy decided to trade). Used to attribute round-trip P&L
    # back to the signals/filters that caused entries. See SignalEvent.
    tags: tuple[str, ...] = ()


# ============================================================
# Position tracking
# ============================================================
@dataclass
class Position:
    """An open position in one symbol. Mutable; the Portfolio updates it.

    `avg_cost` is the quantity-weighted average price across all entries.
    Realized P&L is accumulated as positions are closed; unrealized P&L
    is not stored here (it depends on a current mark, which varies).
    """

    symbol: str
    quantity: Decimal = Decimal(0)
    avg_cost: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    # Contract multiplier (1 for equity/crypto, 100 for options). Set when the
    # position is first opened; used for cash math and mark-to-market.
    multiplier: Decimal = Decimal(1)


# ============================================================
# Equity curve
# ============================================================
@dataclass(frozen=True)
class EquityPoint:
    """A single mark-to-market snapshot at a bar close."""

    ts: datetime
    cash: Decimal
    positions_value: Decimal
    total_equity: Decimal


# ============================================================
# Aggregate result
# ============================================================
@dataclass
class BacktestResult:
    """Output of run_backtest().

    `rejected_orders` lists orders the engine declined to fill (insufficient
    cash, attempting to sell more than held). The reason string explains why.

    `cancelled_orders` and `expired_orders` track lifecycle events for
    diagnostic / reporting purposes; the strategy was already notified
    via its on_order_* callbacks.

    `strategy_state_final` is a snapshot of the strategy's `self.state` dict
    at the end of the run, useful for debugging strategy logic.
    """

    config: BacktestConfig
    fills: list[Fill] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    final_cash: Decimal = Decimal(0)
    final_positions: dict[str, Position] = field(default_factory=dict)
    rejected_orders: list[tuple[Order, str]] = field(default_factory=list)
    cancelled_orders: list[Order] = field(default_factory=list)
    expired_orders: list[Order] = field(default_factory=list)
    strategy_state_final: dict[str, Any] = field(default_factory=dict)
    # Every signal/filter event the strategy emitted, in chronological order.
    # Drives attribution analytics (the "why"). Empty for strategies that
    # never call ctx.signal().
    signal_events: list["SignalEvent"] = field(default_factory=list)
    # Total orders the strategy submitted across the run. 0 ⇒ the strategy never
    # tried to trade (a dead/impossible entry condition), as opposed to trading
    # but never closing a round trip. Drives the 0-trade diagnostic.
    orders_submitted: int = 0

    @property
    def final_equity(self) -> Decimal:
        if not self.equity_curve:
            return self.final_cash
        return self.equity_curve[-1].total_equity

    @property
    def total_return_pct(self) -> Decimal:
        if self.config.starting_cash == 0:
            return Decimal(0)
        return (self.final_equity / self.config.starting_cash - Decimal(1)) * Decimal(100)

    @property
    def num_trades(self) -> int:
        return len(self.fills)

    @property
    def num_rejected(self) -> int:
        return len(self.rejected_orders)

    @property
    def num_cancelled(self) -> int:
        return len(self.cancelled_orders)

    @property
    def num_expired(self) -> int:
        return len(self.expired_orders)
