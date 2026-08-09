-- Supabase / Postgres canonical schema for the Catalyst Breakout system.
-- The offline sqlite path mirrors this (see src/catalyst/store/db.py SQLITE_SCHEMA).
--
-- Design note: the panel is keyed for point-in-time reads. Fundamentals and
-- catalysts carry a knowable_at column (filing acceptance / market-knowable
-- timestamp), and ALL point-in-time queries filter on it -- never on period_end
-- or event_date. This is the structural enforcement of anti-bias rule #4.

BEGIN;

-- Survivorship-correct universe membership. delisted_date non-null => the name
-- later delisted but MUST remain in the as-of universe for any date it was live.
CREATE TABLE IF NOT EXISTS universe (
    ticker        TEXT NOT NULL,
    as_of         DATE NOT NULL,
    active        BOOLEAN NOT NULL,
    delisted_date DATE,
    optionable    BOOLEAN NOT NULL DEFAULT FALSE,
    market_cap    DOUBLE PRECISION,
    PRIMARY KEY (ticker, as_of)
);

CREATE TABLE IF NOT EXISTS prices (
    ticker    TEXT NOT NULL,
    date      DATE NOT NULL,
    open      DOUBLE PRECISION,
    high      DOUBLE PRECISION,
    low       DOUBLE PRECISION,
    close     DOUBLE PRECISION,
    volume    DOUBLE PRECISION,
    adj_close DOUBLE PRECISION,          -- split/dividend adjusted
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker         TEXT NOT NULL,
    period_end     DATE NOT NULL,
    knowable_at    DATE NOT NULL,        -- filing acceptance date (PIT key)
    fcf            DOUBLE PRECISION,
    gross_margin   DOUBLE PRECISION,
    op_margin      DOUBLE PRECISION,
    debt_to_equity DOUBLE PRECISION,
    as_reported    BOOLEAN NOT NULL DEFAULT TRUE,   -- as-reported, not restated
    PRIMARY KEY (ticker, period_end)
);
CREATE INDEX IF NOT EXISTS idx_fund_knowable ON fundamentals(ticker, knowable_at);

CREATE TABLE IF NOT EXISTS catalysts (
    catalyst_id     TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    catalyst_type   TEXT NOT NULL,
    source          TEXT NOT NULL,
    knowable_at     TIMESTAMPTZ NOT NULL,   -- mandatory; backtester keys entry off this
    event_date      DATE,
    tier            TEXT NOT NULL CHECK (tier IN ('structured','validator')),
    requires_review BOOLEAN NOT NULL DEFAULT FALSE,
    payload         JSONB
);
CREATE INDEX IF NOT EXISTS idx_catalysts_knowable ON catalysts(ticker, knowable_at);

CREATE TABLE IF NOT EXISTS iv_snapshots (
    ticker TEXT NOT NULL,
    date   DATE NOT NULL,
    atm_iv DOUBLE PRECISION,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id    TEXT PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    ticker       TEXT NOT NULL,
    payload      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);

COMMIT;
