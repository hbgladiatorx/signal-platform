"""Per-session isolated equity accounting."""
from __future__ import annotations

from decimal import Decimal

from packages.livetrade.session import isolated_equity_from_positions


def _mark(prices: dict[str, Decimal]):
    return lambda sym: prices.get(sym)


def test_untraded_session_is_flat_at_starting_cash() -> None:
    cash, pv, equity, realized = isolated_equity_from_positions(
        [], _mark({}), Decimal("100000")
    )
    assert equity == Decimal("100000")
    assert cash == Decimal("100000")
    assert pv == Decimal("0")
    assert realized == Decimal("0")


def test_open_long_marks_to_market() -> None:
    rows = [{"symbol": "SPY", "quantity": Decimal("10"), "avg_cost": Decimal("100"),
             "realized_pnl": Decimal("0")}]
    cash, pv, equity, realized = isolated_equity_from_positions(
        rows, _mark({"SPY": Decimal("110")}), Decimal("100000")
    )
    # bought 10 @100 -> cash 100000-1000=99000; position now worth 10*110=1100
    assert pv == Decimal("1100")
    assert cash == Decimal("99000")
    assert equity == Decimal("100100")  # +100 unrealized
    assert realized == Decimal("0")


def test_realized_pnl_included_after_close() -> None:
    rows = [{"symbol": "SPY", "quantity": Decimal("0"), "avg_cost": Decimal("0"),
             "realized_pnl": Decimal("250")}]
    cash, pv, equity, realized = isolated_equity_from_positions(
        rows, _mark({}), Decimal("100000")
    )
    assert realized == Decimal("250")
    assert equity == Decimal("100250")
    assert pv == Decimal("0")
    assert cash == Decimal("100250")


def test_missing_price_falls_back_to_cost_basis() -> None:
    rows = [{"symbol": "SPY", "quantity": Decimal("5"), "avg_cost": Decimal("100"),
             "realized_pnl": Decimal("0")}]
    _cash, pv, equity, _r = isolated_equity_from_positions(
        rows, _mark({}), Decimal("100000")  # no price -> mark at avg_cost
    )
    assert pv == Decimal("500")
    assert equity == Decimal("100000")  # no unrealized when marked at cost


def test_option_multiplier_applied() -> None:
    rows = [{"symbol": "SPY_C", "quantity": Decimal("2"), "avg_cost": Decimal("3"),
             "realized_pnl": Decimal("0")}]
    _cash, pv, equity, _r = isolated_equity_from_positions(
        rows, _mark({"SPY_C": Decimal("4")}), Decimal("100000"), Decimal("100")
    )
    assert pv == Decimal("800")  # 2 * 4 * 100
    assert equity == Decimal("100200")  # 2 * (4-3) * 100 unrealized
