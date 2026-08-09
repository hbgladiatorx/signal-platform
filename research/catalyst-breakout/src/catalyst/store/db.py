"""Database connection + schema bootstrap.

Offline/test default is stdlib sqlite3 (no external service needed). Production
sets DATABASE_URL to a Supabase Postgres URL; the same SQL applies (the
migrations/ dir holds the canonical Postgres DDL). This module gives the rest of
the system a uniform cursor/exec interface so the PIT panel code is storage-
agnostic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker        TEXT NOT NULL,
    as_of         TEXT NOT NULL,   -- date this membership row is knowable
    active        INTEGER NOT NULL,
    delisted_date TEXT,            -- non-null => later delisted (survivorship)
    optionable    INTEGER NOT NULL DEFAULT 0,
    market_cap    REAL,
    PRIMARY KEY (ticker, as_of)
);

CREATE TABLE IF NOT EXISTS prices (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL, high REAL, low REAL, close REAL, volume REAL,
    adj_close REAL,                -- split/dividend adjusted
    PRIMARY KEY (ticker, date)
);

-- Fundamentals are stamped with knowable_at = filing acceptance date, NOT
-- period_end. The PIT layer filters on knowable_at, never period_end.
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker       TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    knowable_at  TEXT NOT NULL,    -- filing acceptance date
    fcf          REAL,
    gross_margin REAL,
    op_margin    REAL,
    debt_to_equity REAL,
    as_reported  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (ticker, period_end)
);

-- Every catalyst carries knowable_at (mandatory) -- the backtester keys entry
-- off this and NEVER off the event date.
CREATE TABLE IF NOT EXISTS catalysts (
    catalyst_id   TEXT PRIMARY KEY,
    ticker        TEXT NOT NULL,
    catalyst_type TEXT NOT NULL,
    source        TEXT NOT NULL,
    knowable_at   TEXT NOT NULL,
    event_date    TEXT,
    tier          TEXT NOT NULL,   -- 'structured' | 'validator'
    requires_review INTEGER NOT NULL DEFAULT 0,
    payload       TEXT             -- JSON detail
);

CREATE TABLE IF NOT EXISTS iv_snapshots (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    atm_iv  REAL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id    TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    payload      TEXT NOT NULL     -- full Section 8 JSON payload
);

CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
CREATE INDEX IF NOT EXISTS idx_catalysts_knowable ON catalysts(ticker, knowable_at);
CREATE INDEX IF NOT EXISTS idx_fund_knowable ON fundamentals(ticker, knowable_at);
"""


class Database:
    """Thin wrapper over a DB-API connection (sqlite3 by default)."""

    def __init__(self, url: str = "sqlite:///catalyst.db"):
        self.url = url
        if url.startswith("sqlite"):
            path = url.replace("sqlite:///", "", 1)
            if path == ":memory:" or url.endswith(":memory:"):
                self.conn = sqlite3.connect(":memory:")
            else:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.flavor = "sqlite"
        else:  # pragma: no cover - requires psycopg + live DB
            import psycopg

            self.conn = psycopg.connect(url, row_factory=psycopg.rows.dict_row)
            self.flavor = "postgres"

    def bootstrap(self) -> None:
        if self.flavor == "sqlite":
            self.conn.executescript(SQLITE_SCHEMA)
            self.conn.commit()
        # Postgres uses migrations/ DDL applied out-of-band.

    def execute(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(self._adapt(sql), tuple(params))
        try:
            rows = cur.fetchall()
        except sqlite3.ProgrammingError:
            rows = []
        self.conn.commit()
        return [dict(r) for r in rows]

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        cur = self.conn.cursor()
        cur.executemany(self._adapt(sql), [tuple(r) for r in rows])
        self.conn.commit()

    def _adapt(self, sql: str) -> str:
        # Postgres uses %s placeholders; sqlite uses ?. We author in ? and
        # translate for postgres.
        if self.flavor == "postgres":
            return sql.replace("?", "%s")
        return sql

    def close(self) -> None:
        self.conn.close()
