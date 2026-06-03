"""Portfolio — cash and per-symbol positions with average-cost accounting.

Phase 2 supports long-only, cash-only trading. Shorting and margin will be
added in later phases.

Average-cost accounting:
  - On buy: new_avg_cost = (old_qty * old_avg + new_qty * new_price) / total_qty
    Fees are deducted from cash but not folded into avg_cost. This is a
    research-friendly convention; for tax accounting you'd want fees in the
    basis. The total return on the equity curve is unaffected by this choice.
  - On sell: realized P&L = (sell_price - avg_cost) * quantity - sell_fee
    avg_cost remains unchanged until the position fully closes, at which
    point it resets to 0.
"""
from __future__ import annotations

from decimal import Decimal

from packages.backtest.types import Position


class Portfolio:
    """Tracks cash and per-symbol positions."""

    def __init__(self, starting_cash: Decimal) -> None:
        self.cash: Decimal = starting_cash
        self.positions: dict[str, Position] = {}

    def get_position(self, symbol: str) -> Position:
        """Return the Position for symbol (creating a zero one if needed)."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def positions_for_context(self) -> dict[str, Decimal]:
        """Quantity-only view for BarContext; omits zero positions."""
        return {
            sym: pos.quantity
            for sym, pos in self.positions.items()
            if pos.quantity != 0
        }

    def apply_buy(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        multiplier: Decimal = Decimal(1),
    ) -> None:
        """Apply a buy fill: deduct cash, update qty and weighted-avg cost.

        `multiplier` is the contract multiplier (1 for equity/crypto, 100 for
        options); it scales the cash notional but not the per-unit avg_cost.
        """
        cost = quantity * price * multiplier + fee
        self.cash -= cost

        pos = self.get_position(symbol)
        if pos.quantity == 0:
            pos.avg_cost = price
            pos.multiplier = multiplier
        else:
            # Quantity-weighted average. Fees not included in basis.
            new_basis_total = pos.quantity * pos.avg_cost + quantity * price
            new_quantity = pos.quantity + quantity
            pos.avg_cost = new_basis_total / new_quantity
        pos.quantity += quantity

    def apply_sell(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
    ) -> None:
        """Apply a sell fill: add proceeds (net of fee), realize P&L.

        The contract multiplier is read from the open position (set on buy)."""
        pos = self.get_position(symbol)
        mult = pos.multiplier
        proceeds = quantity * price * mult - fee
        self.cash += proceeds

        gross_pnl = (price - pos.avg_cost) * quantity * mult
        pos.realized_pnl += gross_pnl - fee
        pos.quantity -= quantity
        if pos.quantity == 0:
            pos.avg_cost = Decimal(0)

    def mark_to_market(self, marks: dict[str, Decimal]) -> Decimal:
        """Sum of position quantity × mark × multiplier for all open positions.

        Symbols missing from `marks` contribute 0 — callers should
        carry-forward their most recent known mark.
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
