"""position_math correctness + parity with the backtest Portfolio.

The live reconciler and the backtest engine must agree on average-cost
accounting, so these assert the shared math matches Portfolio bit-for-bit.
"""
from __future__ import annotations

from decimal import Decimal as D

from packages.backtest.portfolio import Portfolio
from packages.livetrade.position_math import PositionState, apply_buy, apply_sell


def test_buy_then_buy_weighted_average():
    s = apply_buy(PositionState(), D("2"), D("100"))
    s = apply_buy(s, D("2"), D("200"))
    assert s.quantity == D("4")
    assert s.avg_cost == D("150")


def test_sell_realizes_pnl_minus_fee():
    s = apply_buy(PositionState(), D("4"), D("150"))
    s = apply_sell(s, D("1"), D("180"), D("1"))
    # (180 - 150) * 1 - 1 fee = 29
    assert s.realized_pnl == D("29")
    assert s.quantity == D("3")
    assert s.avg_cost == D("150")  # avg held until fully closed


def test_full_close_resets_avg_cost():
    s = apply_buy(PositionState(), D("3"), D("150"))
    s = apply_sell(s, D("3"), D("160"), D("0"))
    assert s.quantity == D("0")
    assert s.avg_cost == D("0")


def test_parity_with_portfolio():
    """Same fills through Portfolio and position_math → identical state."""
    pf = Portfolio(starting_cash=D("100000"))
    st = PositionState()
    fills = [
        ("buy", D("2"), D("100"), D("0.5")),
        ("buy", D("3"), D("120"), D("0.7")),
        ("sell", D("1"), D("130"), D("0.2")),
        ("buy", D("1"), D("90"), D("0.1")),
        ("sell", D("5"), D("110"), D("0.4")),
    ]
    for side, qty, price, fee in fills:
        if side == "buy":
            pf.apply_buy("X", qty, price, fee)
            st = apply_buy(st, qty, price)
        else:
            pf.apply_sell("X", qty, price, fee)
            st = apply_sell(st, qty, price, fee)

    pos = pf.get_position("X")
    assert st.quantity == pos.quantity
    assert st.avg_cost == pos.avg_cost
    assert st.realized_pnl == pos.realized_pnl
