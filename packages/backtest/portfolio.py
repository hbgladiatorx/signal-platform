"""Portfolio — cash and per-symbol positions with average-cost accounting.

Supports LONG and SHORT positions with a configurable margin requirement.
Position quantity is signed: positive = long, negative = short, 0 = flat.

Average-cost accounting:
  - Increasing a position (same direction): new_avg = quantity-weighted average
    of the old basis and the new fill. Fees leave cash but are not folded into
    the basis (a research-friendly convention; total return is unaffected).
  - Reducing/closing/flipping (opposite direction): realize P&L on the closed
    quantity — (price - avg_cost) for a long, (avg_cost - price) for a short —
    times the contract multiplier, minus the fee. If the fill flips the sign
    (e.g. long 10, sell 15 → short 5) the residual opens a new position at the
    fill price.

Cash flow: buying spends cash; selling/shorting receives cash (short proceeds
are credited and offset by the negative position value, so equity only moves by
fees at the moment of opening a short). mark_to_market sums signed qty × mark ×
multiplier, so a short contributes a negative (liability) value automatically.

Margin: equity = cash + Σ position market value; gross exposure = Σ |position
market value|. A fill that INCREASES gross exposure is only accepted if the
post-fill equity covers `margin_rate × gross_exposure` (1.0 = fully
collateralized / no leverage; 0.5 = 2:1). Reductions/closes are always allowed.
"""
from __future__ import annotations

from decimal import Decimal

from packages.strategy.base import OrderSide
from packages.backtest.types import Position


class Portfolio:
    """Tracks cash and per-symbol signed positions (long or short)."""

    def __init__(self, starting_cash: Decimal) -> None:
        self.cash: Decimal = starting_cash
        self.positions: dict[str, Position] = {}

    def get_position(self, symbol: str) -> Position:
        """Return the Position for symbol (creating a zero one if needed)."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def positions_for_context(self) -> dict[str, Decimal]:
        """Signed quantity view for BarContext; omits flat positions."""
        return {
            sym: pos.quantity
            for sym, pos in self.positions.items()
            if pos.quantity != 0
        }

    # ------------------------------------------------------------------
    # Fill application
    # ------------------------------------------------------------------
    def apply_fill(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        multiplier: Decimal = Decimal(1),
    ) -> None:
        """Apply a fill (buy or sell) to cash and the signed position.

        Handles opening/increasing a long or short, reducing, closing, and
        flipping through zero in a single call.
        """
        signed = quantity if side == OrderSide.BUY else -quantity
        # Buying spends cash (signed > 0 → subtract); selling/shorting receives.
        self.cash -= signed * price * multiplier
        self.cash -= fee

        pos = self.get_position(symbol)
        old = pos.quantity
        new = old + signed
        same_direction = (old > 0 and signed > 0) or (old < 0 and signed < 0)

        if old == 0:
            pos.avg_cost = price
            pos.multiplier = multiplier
        elif same_direction:
            total = abs(old) + abs(signed)
            pos.avg_cost = (abs(old) * pos.avg_cost + abs(signed) * price) / total
        else:
            # Opposite direction → realize P&L on the closed portion.
            closed = min(abs(signed), abs(old))
            if old > 0:  # closing/reducing a long
                gross_pnl = (price - pos.avg_cost) * closed * pos.multiplier
            else:        # closing/reducing a short
                gross_pnl = (pos.avg_cost - price) * closed * pos.multiplier
            pos.realized_pnl += gross_pnl - fee
            if abs(signed) > abs(old):
                # Flipped through zero — residual opens a new position.
                pos.avg_cost = price
                pos.multiplier = multiplier
            elif new == 0:
                pos.avg_cost = Decimal(0)
            # else: partial reduce — avg_cost stays put.

        pos.quantity = new

    # Back-compat thin wrappers (older callers / tests).
    def apply_buy(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        multiplier: Decimal = Decimal(1),
    ) -> None:
        self.apply_fill(symbol, OrderSide.BUY, quantity, price, fee, multiplier)

    def apply_sell(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        multiplier: Decimal | None = None,
    ) -> None:
        pos = self.get_position(symbol)
        mult = pos.multiplier if multiplier is None else multiplier
        self.apply_fill(symbol, OrderSide.SELL, quantity, price, fee, mult)

    # ------------------------------------------------------------------
    # Valuation / margin
    # ------------------------------------------------------------------
    def mark_to_market(self, marks: dict[str, Decimal]) -> Decimal:
        """Sum of signed quantity × mark × multiplier for all open positions.

        Shorts (negative quantity) contribute a negative (liability) value.
        Symbols missing from `marks` contribute 0 — callers should carry
        forward their most recent known mark.
        """
        total = Decimal(0)
        for sym, pos in self.positions.items():
            if pos.quantity == 0:
                continue
            mark = marks.get(sym)
            if mark is None:
                continue
            total += pos.quantity * mark * pos.multiplier
        return total

    def projected_equity_and_gross(
        self,
        cash_after: Decimal,
        marks: dict[str, Decimal],
        symbol: str,
        new_qty: Decimal,
        multiplier: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Hypothetical (equity, gross_exposure) if `symbol` becomes `new_qty`.

        Used for the pre-fill buying-power check. equity = cash_after + Σ MV;
        gross = Σ |MV|, where the target symbol uses `new_qty`/`multiplier` and
        all others keep their current quantity.
        """
        equity = cash_after
        gross = Decimal(0)
        seen = False
        for sym, pos in self.positions.items():
            if sym == symbol:
                qty, mult = new_qty, multiplier
                seen = True
            else:
                qty, mult = pos.quantity, pos.multiplier
            if qty == 0:
                continue
            mark = marks.get(sym)
            if mark is None:
                continue
            mv = qty * mark * mult
            equity += mv
            gross += abs(mv)
        if not seen and new_qty != 0:
            mark = marks.get(symbol)
            if mark is not None:
                mv = new_qty * mark * multiplier
                equity += mv
                gross += abs(mv)
        return equity, gross
