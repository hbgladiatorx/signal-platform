-- Migration 0008: Live + paper trading execution tables.
--
-- New tables:
--   trading_accounts  — one per (user, mode) trading book. Paper accounts carry
--                       an authoritative simulated cash balance; live accounts
--                       reference an api_credentials row for the venue keys.
--   orders            — every order placed through the execution layer.
--   order_fills       — individual executions against an order.
--   trading_positions — net spot position per (account, symbol).
--
-- All child tables cascade from trading_accounts so deleting an account cleans
-- up its orders, fills, and positions.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- trading_accounts
-- ============================================================
CREATE TABLE IF NOT EXISTS trading_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    venue           TEXT NOT NULL DEFAULT 'BINANCEUS',
    quote_currency  TEXT NOT NULL DEFAULT 'USDT',

    -- Paper bookkeeping (authoritative for mode='paper'; informational for live)
    starting_cash   NUMERIC NOT NULL DEFAULT 0,
    cash_balance    NUMERIC NOT NULL DEFAULT 0,

    -- Live execution: which stored credential to sign with (NULL => env fallback)
    credential_id   UUID REFERENCES api_credentials(id) ON DELETE SET NULL,

    -- Paper fill model knobs
    fee_bps         INTEGER NOT NULL DEFAULT 10,
    slippage_bps    INTEGER NOT NULL DEFAULT 5,

    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trading_accounts_user
    ON trading_accounts (user_id, created_at DESC);


-- ============================================================
-- orders
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    canonical_symbol TEXT NOT NULL,
    native_symbol    TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type       TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    quantity         NUMERIC NOT NULL CHECK (quantity > 0),
    limit_price      NUMERIC,

    mode             TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    status           TEXT NOT NULL DEFAULT 'new'
                     CHECK (status IN ('new', 'partially_filled', 'filled',
                                       'canceled', 'rejected', 'expired')),
    filled_quantity  NUMERIC NOT NULL DEFAULT 0,
    avg_fill_price   NUMERIC,
    fees             NUMERIC NOT NULL DEFAULT 0,
    fee_currency     TEXT,

    client_order_id  TEXT NOT NULL,
    venue_order_id   TEXT,
    error_message    TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (account_id, client_order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_account_created
    ON orders (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_user_created
    ON orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_open
    ON orders (account_id, status)
    WHERE status IN ('new', 'partially_filled');


-- ============================================================
-- order_fills
-- ============================================================
CREATE TABLE IF NOT EXISTS order_fills (
    id            BIGSERIAL PRIMARY KEY,
    order_id      UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    account_id    UUID NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    price         NUMERIC NOT NULL,
    quantity      NUMERIC NOT NULL,
    fee           NUMERIC NOT NULL DEFAULT 0,
    fee_currency  TEXT,
    venue_fill_id TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_fills_order
    ON order_fills (order_id, ts);
CREATE INDEX IF NOT EXISTS idx_order_fills_account
    ON order_fills (account_id, ts DESC);


-- ============================================================
-- trading_positions — net spot position per (account, symbol)
-- ============================================================
CREATE TABLE IF NOT EXISTS trading_positions (
    account_id       UUID NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    canonical_symbol TEXT NOT NULL,
    quantity         NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price  NUMERIC NOT NULL DEFAULT 0,
    realized_pnl     NUMERIC NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, canonical_symbol)
);
