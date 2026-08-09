"""ANTI-BIAS RULE #4 -- Point-in-time fundamentals lagged to filing.

Fundamentals must be keyed off the FILING acceptance date (knowable_at), not the
period end. A quarter is only known after it was filed.
"""

from datetime import date

from catalyst.store.panel import AsOfPanel
from catalyst.pit.features import get_pit_features
from config.defaults import DEFAULTS
from conftest import seed_prices, seed_universe, seed_fundamentals


def test_quarter_not_visible_until_filed(db):
    t = "TESTF"
    seed_prices(db, t, date(2022, 1, 3), [10.0] * 300)
    seed_universe(db, t, date(2022, 1, 3))

    # Q1 ends 2022-03-31 but is not filed/accepted until 2022-05-06.
    seed_fundamentals(db, t, period_end=date(2022, 3, 31),
                      knowable_at=date(2022, 5, 6), fcf=99.0, op_margin=0.5)

    # As of 2022-04-15 (after period end, before filing): must NOT be visible.
    panel_before = AsOfPanel(db, date(2022, 4, 15))
    funds_before = panel_before.fundamentals(t)
    assert all(f["knowable_at"] <= "2022-04-15" for f in funds_before)
    assert not any(f["period_end"] == "2022-03-31" for f in funds_before)

    # As of 2022-05-10 (after filing): now visible.
    panel_after = AsOfPanel(db, date(2022, 5, 10))
    funds_after = panel_after.fundamentals(t)
    assert any(f["period_end"] == "2022-03-31" for f in funds_after)


def test_feature_row_uses_knowable_fundamentals_only(db):
    t = "TESTG"
    seed_prices(db, t, date(2022, 1, 3), [10.0] * 300)
    seed_universe(db, t, date(2022, 1, 3))
    # Four improving quarters, the last one filed AFTER as_of.
    seed_fundamentals(db, t, date(2021, 9, 30), date(2021, 11, 5), fcf=1.0, op_margin=0.01)
    seed_fundamentals(db, t, date(2021, 12, 31), date(2022, 2, 5), fcf=2.0, op_margin=0.02)
    seed_fundamentals(db, t, date(2022, 3, 31), date(2022, 5, 5), fcf=3.0, op_margin=0.03)
    seed_fundamentals(db, t, date(2022, 6, 30), date(2022, 8, 5), fcf=99.0, op_margin=0.9)

    panel = AsOfPanel(db, date(2022, 6, 15))  # before the last filing
    row = get_pit_features(t, date(2022, 6, 15), panel, DEFAULTS)
    # The latest knowable snapshot must be the Q1 (filed 5/5), not the unfiled Q2.
    assert row.fundamental_snapshot["knowable_at"] == "2022-05-05"
    assert row.fundamental_snapshot["fcf"] == 3.0
