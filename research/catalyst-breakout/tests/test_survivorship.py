"""ANTI-BIAS RULE #3 -- Survivorship.

A name that was live as of the decision date but later delisted MUST appear in
the as-of universe. The universe view must not be survivor-only.
"""

from datetime import date

from catalyst.store.panel import AsOfPanel
from conftest import seed_universe


def test_later_delisted_name_is_in_as_of_universe(db):
    as_of = date(2020, 6, 1)
    # SURVIVOR: still active today.
    seed_universe(db, "SURV", as_of=date(2020, 1, 2), optionable=True, active=True)
    # DELISTED LATER: was live on as_of, delisted in 2021. Must still be included.
    seed_universe(db, "DEAD", as_of=date(2020, 1, 2), optionable=True,
                  active=True, delisted_date=date(2021, 3, 15))

    panel = AsOfPanel(db, as_of)
    tickers = {u["ticker"] for u in panel.universe(optionable_only=True)}

    assert "SURV" in tickers
    assert "DEAD" in tickers, "later-delisted name dropped -> survivorship bias"


def test_membership_added_after_as_of_is_excluded(db):
    as_of = date(2020, 6, 1)
    # Name only enters the universe AFTER as_of -> must not appear.
    seed_universe(db, "NEWB", as_of=date(2021, 1, 4), optionable=True, active=True)

    panel = AsOfPanel(db, as_of)
    tickers = {u["ticker"] for u in panel.universe(optionable_only=True)}
    assert "NEWB" not in tickers
