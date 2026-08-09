"""ANTI-BIAS RULE #6 -- archetypes are the pattern source, NOT a scorecard.

The system must contain NO branch, weight, or threshold chosen to make INTC, NOK,
DELL, or MU specifically appear as winners. We enforce this structurally: the
archetype tickers must not appear as string literals anywhere in the decision
path (screen / catalysts / options / signals / backtest), and the engine must
treat an archetype name identically to any synthetic name with the same data.
"""

import re
from pathlib import Path

import pytest

from config.defaults import DEFAULTS

DECISION_PATH = [
    "screen", "catalysts", "options", "signals", "backtest", "pit",
]
SRC = Path(__file__).resolve().parents[1] / "src" / "catalyst"


def test_archetypes_absent_from_decision_path_source():
    offenders = []
    for pkg in DECISION_PATH:
        for py in (SRC / pkg).rglob("*.py"):
            text = py.read_text()
            for name in DEFAULTS.archetype_names:
                # Word-boundary match for the bare ticker as a literal.
                if re.search(rf"['\"]{name}['\"]", text) or re.search(rf"\b{name}\b", text):
                    offenders.append(f"{py}: references {name}")
    assert not offenders, (
        "Archetype tickers leaked into the decision path (rule #6):\n"
        + "\n".join(offenders)
    )


def test_archetype_names_only_live_in_config_for_this_test():
    # They are exposed in config ONLY so this test can assert their absence
    # elsewhere. The config docstring marks them as never read by signal logic.
    assert set(DEFAULTS.archetype_names) == {"INTC", "NOK", "DELL", "MU"}


def test_engine_treats_archetype_name_identically(db):
    """Same data under an archetype ticker vs a synthetic ticker => same decision."""
    from datetime import date, timedelta
    from catalyst.backtest.engine import run_signal
    from conftest import (seed_universe, seed_prices, seed_fundamentals,
                          seed_catalyst, seed_iv)

    start = date(2022, 1, 3)
    closes = [100.0] * 130 + [50.0 - i * 0.05 for i in range(130)]

    def build(ticker):
        seed_prices(db, ticker, start, closes)
        seed_universe(db, ticker, start, market_cap=1_000_000_000.0, optionable=True)
        for i, (fcf, m) in enumerate([(1, 0.01), (2, 0.02), (3, 0.04), (5, 0.08)]):
            seed_fundamentals(db, ticker, period_end=start + timedelta(days=i),
                              knowable_at=start + timedelta(days=i), fcf=fcf, op_margin=m)
        seed_iv(db, ticker, start, [0.4] * len(closes))
        as_of = start + timedelta(days=250)
        seed_catalyst(db, ticker, knowable_at=as_of,
                      payload={"surprise_pct": 12.0, "guidance_raise": True})
        return as_of

    as_of = build("INTC")          # an archetype name
    build("ZZZZ")                  # a synthetic control with identical data

    t_arch = run_signal(db, "INTC", as_of, cfg=DEFAULTS)
    t_ctrl = run_signal(db, "ZZZZ", as_of, cfg=DEFAULTS)

    assert (t_arch is None) == (t_ctrl is None)
    assert t_arch.filled == t_ctrl.filled
    assert t_arch.catalyst_type == t_ctrl.catalyst_type
    # Identical inputs => identical realized return. No archetype favoritism.
    assert t_arch.rules_return == pytest.approx(t_ctrl.rules_return)
