"""The point-in-time panel access layer -- the hard enforcement of anti-bias rule #1.

``AsOfPanel`` is constructed bound to a single ``as_of`` date. EVERY read method
it exposes appends a hard ``<= as_of`` predicate at the QUERY layer. There is no
method on this class that can return a record dated after ``as_of``. This is the
"physically incapable of reading future data" guarantee from Section 3.

The test suite (tests/test_no_lookahead.py) constructs a panel, seeds a future-
dated record, and asserts the panel cannot see it.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from .db import Database


def _as_iso(d: date | str) -> str:
    if isinstance(d, str):
        # Validate it parses as a date; reject garbage so the filter is sound.
        datetime.fromisoformat(d[:10])
        return d[:10]
    return d.isoformat()


class LookaheadError(AssertionError):
    """Raised if code attempts to bypass the as_of boundary."""


class AsOfPanel:
    """Read-only, point-in-time-bounded view of the panel as of one date."""

    def __init__(self, db: Database, as_of: date | str):
        self.db = db
        self.as_of = _as_iso(as_of)

    # -- prices ------------------------------------------------------------
    def price_history(self, ticker: str, lookback_days: int | None = None) -> list[dict[str, Any]]:
        """Adjusted daily bars for ticker with date <= as_of (hard filter)."""
        sql = (
            "SELECT ticker, date, open, high, low, close, volume, adj_close "
            "FROM prices WHERE ticker = ? AND date <= ? ORDER BY date ASC"
        )
        rows = self.db.execute(sql, (ticker, self.as_of))
        if lookback_days is not None:
            rows = rows[-lookback_days:]
        self._assert_no_future(rows, "date")
        return rows

    def latest_price(self, ticker: str) -> dict[str, Any] | None:
        rows = self.price_history(ticker)
        return rows[-1] if rows else None

    # -- fundamentals (lagged to filing knowable_at) ----------------------
    def fundamentals(self, ticker: str) -> list[dict[str, Any]]:
        """As-reported fundamentals KNOWABLE as of as_of (filter on knowable_at).

        We filter on knowable_at (filing acceptance), never period_end. A quarter
        is only known after it was filed (anti-bias rule #4).
        """
        sql = (
            "SELECT ticker, period_end, knowable_at, fcf, gross_margin, op_margin, "
            "debt_to_equity, as_reported FROM fundamentals "
            "WHERE ticker = ? AND knowable_at <= ? ORDER BY period_end ASC"
        )
        rows = self.db.execute(sql, (ticker, self.as_of))
        self._assert_no_future(rows, "knowable_at")
        return rows

    # -- catalysts (keyed off knowable_at) --------------------------------
    def catalysts(self, ticker: str, since_days: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT catalyst_id, ticker, catalyst_type, source, knowable_at, "
            "event_date, tier, requires_review, payload FROM catalysts "
            "WHERE ticker = ? AND knowable_at <= ? ORDER BY knowable_at ASC"
        )
        rows = self.db.execute(sql, (ticker, self.as_of))
        if since_days is not None:
            cutoff = (date.fromisoformat(self.as_of) - _days(since_days)).isoformat()
            rows = [r for r in rows if r["knowable_at"] >= cutoff]
        for r in rows:
            if r.get("payload"):
                try:
                    r["payload"] = json.loads(r["payload"])
                except (json.JSONDecodeError, TypeError):
                    pass
        self._assert_no_future(rows, "knowable_at")
        return rows

    # -- IV snapshots ------------------------------------------------------
    def iv_history(self, ticker: str, window: int) -> list[dict[str, Any]]:
        sql = (
            "SELECT ticker, date, atm_iv FROM iv_snapshots "
            "WHERE ticker = ? AND date <= ? ORDER BY date ASC"
        )
        rows = self.db.execute(sql, (ticker, self.as_of))[-window:]
        self._assert_no_future(rows, "date")
        return rows

    # -- universe (survivorship-correct) ----------------------------------
    def universe(self, optionable_only: bool = True) -> list[dict[str, Any]]:
        """Universe membership knowable as of as_of, INCLUDING names that later
        delisted. We take the most recent membership row per ticker with
        as_of <= panel as_of -- delisted names that were live then stay in.
        """
        sql = (
            "SELECT ticker, MAX(as_of) AS as_of, optionable, market_cap, "
            "delisted_date, active FROM universe WHERE as_of <= ? GROUP BY ticker"
        )
        rows = self.db.execute(sql, (self.as_of,))
        if optionable_only:
            rows = [r for r in rows if r.get("optionable")]
        self._assert_no_future(rows, "as_of")
        return rows

    # -- enforcement -------------------------------------------------------
    def _assert_no_future(self, rows: list[dict[str, Any]], date_field: str) -> None:
        """Belt-and-suspenders: assert the query layer actually held the line.

        If any returned row is dated after as_of, the filter failed and we hard
        fail rather than silently leaking future data.
        """
        for r in rows:
            val = r.get(date_field)
            if val and str(val)[:10] > self.as_of:
                raise LookaheadError(
                    f"LOOKAHEAD: row {date_field}={val} > as_of={self.as_of}"
                )


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
