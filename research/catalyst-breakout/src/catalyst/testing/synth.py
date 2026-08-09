"""Synthetic-panel seeding helpers (pytest-free, reusable).

Used by the test suite (tests/conftest.py) AND by scripts/verify.py and the
forward paper-trade harness. Deliberately seeds non-archetype synthetic names so
nothing here can be construed as tuning to INTC/NOK/DELL/MU (anti-bias rule #6).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from ..store.db import Database


def seed_universe(db: Database, ticker: str, as_of: date, *,
                  market_cap=1_000_000_000.0, optionable=True,
                  active=True, delisted_date=None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO universe "
        "(ticker, as_of, active, delisted_date, optionable, market_cap) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, as_of.isoformat(), 1 if active else 0,
         delisted_date.isoformat() if delisted_date else None,
         1 if optionable else 0, market_cap),
    )


def seed_prices(db: Database, ticker: str, start: date, closes: list[float], *,
                volume=2_000_000.0, opens: list[float] | None = None) -> None:
    """Seed a daily series. By default open=prev close (no gaps); pass ``opens``
    to model opening gaps (e.g. to test the do-not-chase reject at the T+1 open)."""
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        d = start + timedelta(days=i)
        o = opens[i] if opens is not None else prev
        hi = max(o, c) * 1.01
        lo = min(o, c) * 0.99
        rows.append((ticker, d.isoformat(), o, hi, lo, c, volume, c))
        prev = c
    db.executemany(
        "INSERT OR REPLACE INTO prices "
        "(ticker, date, open, high, low, close, volume, adj_close) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def seed_fundamentals(db: Database, ticker: str, period_end: date,
                      knowable_at: date, *, fcf=10.0, op_margin=0.1,
                      gross_margin=0.3, debt_to_equity=0.5) -> None:
    db.execute(
        "INSERT OR REPLACE INTO fundamentals "
        "(ticker, period_end, knowable_at, fcf, gross_margin, op_margin, "
        "debt_to_equity, as_reported) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (ticker, period_end.isoformat(), knowable_at.isoformat(),
         fcf, gross_margin, op_margin, debt_to_equity),
    )


def seed_catalyst(db: Database, ticker: str, knowable_at: date, *,
                  catalyst_type="earnings_surprise_guidance_raise",
                  tier="structured", source="synth", requires_review=False,
                  payload=None, event_date=None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO catalysts "
        "(catalyst_id, ticker, catalyst_type, source, knowable_at, event_date, "
        "tier, requires_review, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), ticker, catalyst_type, source, knowable_at.isoformat(),
         event_date.isoformat() if event_date else None, tier,
         1 if requires_review else 0, json.dumps(payload or {})),
    )


def seed_iv(db: Database, ticker: str, start: date, ivs: list[float]) -> None:
    rows = [(ticker, (start + timedelta(days=i)).isoformat(), v) for i, v in enumerate(ivs)]
    db.executemany(
        "INSERT OR REPLACE INTO iv_snapshots (ticker, date, atm_iv) VALUES (?, ?, ?)",
        rows,
    )


def seed_firing_name(db: Database, ticker: str, start: date, *,
                     n_bars: int = 260, drawdown_start: int = 130,
                     iv_level: float = 0.4) -> date:
    """Seed a complete name that passes the screen and carries a fresh catalyst.

    Returns the as_of date on which a catalyst is knowable (signal day).
    """
    peak = [100.0] * drawdown_start
    decline = [50.0 - i * 0.05 for i in range(n_bars - drawdown_start)]
    closes = peak + decline
    seed_prices(db, ticker, start, closes)
    seed_universe(db, ticker, start, market_cap=1_000_000_000.0, optionable=True)
    for i, (fcf, m) in enumerate([(1, 0.01), (2, 0.02), (3, 0.04), (5, 0.08)]):
        seed_fundamentals(db, ticker, period_end=start + timedelta(days=i),
                          knowable_at=start + timedelta(days=i), fcf=fcf, op_margin=m)
    seed_iv(db, ticker, start, [iv_level] * len(closes))
    as_of = start + timedelta(days=n_bars - 10)
    seed_catalyst(db, ticker, knowable_at=as_of,
                  payload={"surprise_pct": 12.0, "guidance_raise": True})
    return as_of
