"""ANTI-BIAS RULE #1 -- No lookahead.

Assert the PIT panel is physically incapable of returning a record dated after
its as_of, by seeding future-dated rows and confirming they are invisible.
"""

from datetime import date, timedelta

from catalyst.store.panel import AsOfPanel
from conftest import seed_prices, seed_fundamentals, seed_catalyst


def test_panel_cannot_see_future_prices(db):
    start = date(2022, 1, 3)
    # 40 days of prices; as_of sits in the middle.
    seed_prices(db, "TESTA", start, [10.0 + i * 0.1 for i in range(40)])
    as_of = start + timedelta(days=20)

    panel = AsOfPanel(db, as_of)
    hist = panel.price_history("TESTA")

    assert hist, "expected some as-of price history"
    assert all(r["date"] <= as_of.isoformat() for r in hist)
    # The last visible bar is exactly as_of, never beyond.
    assert hist[-1]["date"] == as_of.isoformat()


def test_panel_cannot_see_future_fundamentals(db):
    as_of = date(2022, 6, 30)
    # A quarter that ENDED before as_of but was FILED after it must be invisible.
    seed_fundamentals(db, "TESTB", period_end=date(2022, 3, 31),
                      knowable_at=date(2022, 7, 15))  # filed AFTER as_of
    # And one knowable in time.
    seed_fundamentals(db, "TESTB", period_end=date(2021, 12, 31),
                      knowable_at=date(2022, 2, 10))

    panel = AsOfPanel(db, as_of)
    funds = panel.fundamentals("TESTB")

    knowable = {f["knowable_at"] for f in funds}
    assert "2022-02-10" in knowable
    assert "2022-07-15" not in knowable, "filed-after-as_of fundamental leaked"


def test_panel_cannot_see_future_catalyst(db):
    as_of = date(2023, 9, 1)
    seed_catalyst(db, "TESTC", knowable_at=date(2023, 9, 20))  # future
    seed_catalyst(db, "TESTC", knowable_at=date(2023, 8, 25))  # past

    panel = AsOfPanel(db, as_of)
    cats = panel.catalysts("TESTC")
    seen = {c["knowable_at"] for c in cats}

    assert "2023-08-25" in seen
    assert "2023-09-20" not in seen, "future catalyst leaked into as-of view"


def test_assert_no_future_guard_is_active(db):
    """The belt-and-suspenders guard raises if a future row ever slips through."""
    from catalyst.store.panel import AsOfPanel, LookaheadError
    import pytest

    panel = AsOfPanel(db, date(2022, 1, 1))
    with pytest.raises(LookaheadError):
        panel._assert_no_future([{"date": "2025-01-01"}], "date")
