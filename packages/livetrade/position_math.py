"""Average-cost position accounting, shared by backtest and live trading.

This is the single source of truth for how a fill mutates a position so the
live paper-trading ledger (paper_positions) and the backtest Portfolio agree
exactly. Long-only, cash-only — matching packages/backtest/portfolio.py.

Convention (unchanged from the backtest Portfolio):
  - On buy: avg_cost is the quantity-weighted average of prices. Fees are NOT
    folded into the basis (they're deducted from cash separately).
  - On sell: realized P&L = (price - avg_cost) * qty - fee. avg_cost is held
    until the position fully closes, then resets to 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionState:
    """Immutable snapshot of a single symbol's position."""

    quantity: Decimal = Decimal(0)
    avg_cost: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)


def apply_buy(
    state: PositionState,
    quantity: Decimal,
    price: Decimal,
) -> PositionState:
    """Return the new position state after a buy fill (fees excluded from basis)."""
    if state.quantity == 0:
        new_avg = price
    else:
        new_basis_total = state.quantity * state.avg_cost + quantity * price
        new_avg = new_basis_total / (state.quantity + quantity)
    return PositionState(
        quantity=state.quantity + quantity,
        avg_cost=new_avg,
        realized_pnl=state.realized_pnl,
    )


def apply_sell(
    state: PositionState,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
) -> PositionState:
    """Return the new position state after a sell fill, realizing P&L."""
    gross_pnl = (price - state.avg_cost) * quantity
    new_qty = state.quantity - quantity
    new_avg = state.avg_cost if new_qty != 0 else Decimal(0)
    return PositionState(
        quantity=new_qty,
        avg_cost=new_avg,
        realized_pnl=state.realized_pnl + gross_pnl - fee,
    )
