"""ANTI-BIAS RULE #2 -- Next-bar entry, and the do-not-chase reject at T+1.

A confirmed signal on day T must enter at the T+1 OPEN, never on the signal bar,
and the do-not-chase rule must be checked at that T+1 open (so a gap-up past the
do-not-chase level produces NO fill).
"""

from datetime import date, timedelta

from catalyst.store.db import Database
from catalyst.backtest.engine import run_signal
from config.defaults import DEFAULTS
from conftest import (seed_universe, seed_prices, seed_fundamentals,
                      seed_catalyst, seed_iv)


def _setup_firing_name(db: Database, closes: list[float], start: date):
    """Build a name that passes the screen and has a fresh catalyst on day T."""
    t = "TESTD"
    # Distressed: build a high then a 50% drawdown into the as_of window.
    seed_prices(db, t, start, closes)
    last_date = start + timedelta(days=len(closes) - 1)
    seed_universe(db, t, start, market_cap=1_000_000_000.0, optionable=True)
    # Improving fundamentals across 4 quarters, all knowable before as_of.
    for i, (fcf, m) in enumerate([(1, 0.01), (2, 0.02), (3, 0.04), (5, 0.08)]):
        seed_fundamentals(db, t, period_end=start + timedelta(days=i),
                          knowable_at=start + timedelta(days=i), fcf=fcf, op_margin=m)
    seed_iv(db, t, start, [0.4] * len(closes))
    return t, last_date


def test_entry_is_t_plus_one_open(db):
    start = date(2022, 1, 3)
    # 260 bars: a peak then a deep drawdown so the screen's distress test passes.
    closes = [100.0] * 130 + [50.0 - i * 0.05 for i in range(130)]
    t, _ = _setup_firing_name(db, closes, start)

    # Signal on a day with at least one more bar after it.
    sig_idx = 250
    as_of = start + timedelta(days=sig_idx)
    seed_catalyst(db, t, knowable_at=as_of,
                  payload={"surprise_pct": 12.0, "guidance_raise": True})

    trade = run_signal(db, t, as_of, cfg=DEFAULTS)
    assert trade is not None and trade.filled
    # Entry date must be the NEXT calendar bar in our daily series.
    assert trade.entry_date == (as_of + timedelta(days=1)).isoformat()
    assert trade.signal_date == as_of.isoformat()
    assert trade.entry_date > trade.signal_date


def test_do_not_chase_blocks_fill_on_gap_up(db):
    start = date(2022, 1, 3)
    t = "TESTE"
    # Flat base at 40, then the bar AFTER the signal OPENS at 80 (a real gap).
    closes = [40.0] * 256 + [80.0, 80.0, 80.0, 80.0]
    opens = [40.0] * 256 + [80.0, 80.0, 80.0, 80.0]
    seed_prices(db, t, start, closes, opens=opens)
    seed_universe(db, t, start, market_cap=1_000_000_000.0, optionable=True)
    for i, (fcf, m) in enumerate([(1, 0.01), (2, 0.02), (3, 0.04), (5, 0.08)]):
        seed_fundamentals(db, t, period_end=start + timedelta(days=i),
                          knowable_at=start + timedelta(days=i), fcf=fcf, op_margin=m)
    seed_iv(db, t, start, [0.4] * len(closes))

    as_of = start + timedelta(days=255)  # signal on last base bar; entry bar gaps to 80
    seed_catalyst(db, t, knowable_at=as_of,
                  payload={"surprise_pct": 12.0, "guidance_raise": True})

    trade = run_signal(db, t, as_of, cfg=DEFAULTS)
    assert trade is not None
    # The T+1 open gapped far above the do-not-chase level -> no fill.
    assert trade.filled is False
    assert trade.no_fill_reason == "do_not_chase"
