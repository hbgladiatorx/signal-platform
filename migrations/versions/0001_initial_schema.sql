-- ============================================================
-- Migration: 0001_initial_schema
-- Phase 1: foundation tables for multi-user signal platform
--
-- Idempotent where possible: re-running this on an empty DB
-- produces a working schema. Re-running on a populated DB
-- will fail on CREATE TABLE — that's intentional.
-- ============================================================

-- ============================================================
-- Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- ORGANIZATIONS & USERS (multi-tenant foundation)
-- ============================================================

CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    plan_tier       TEXT NOT NULL DEFAULT 'free',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    email           TEXT UNIQUE NOT NULL,
    auth0_sub       TEXT UNIQUE NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ
);

CREATE INDEX idx_users_org ON users(org_id);

-- ============================================================
-- INSTRUMENTS (asset-class agnostic)
-- ============================================================

CREATE TABLE instruments (
    id              BIGSERIAL PRIMARY KEY,
    asset_class     TEXT NOT NULL,
    canonical_symbol TEXT NOT NULL UNIQUE,
    venue           TEXT NOT NULL,
    native_symbol   TEXT NOT NULL,
    base            TEXT,
    quote           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_instruments_venue ON instruments(venue);
CREATE INDEX idx_instruments_asset_class ON instruments(asset_class);

-- ============================================================
-- MARKET DATA (TimescaleDB hypertables)
-- ============================================================

CREATE TABLE trades (
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    ts              TIMESTAMPTZ NOT NULL,
    price           NUMERIC(28, 12) NOT NULL,
    quantity        NUMERIC(28, 12) NOT NULL,
    side            CHAR(1),
    venue_trade_id  TEXT NOT NULL,
    PRIMARY KEY (instrument_id, ts, venue_trade_id)
);

SELECT create_hypertable('trades', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX idx_trades_inst_ts ON trades(instrument_id, ts DESC);

CREATE TABLE quotes_l1 (
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    ts              TIMESTAMPTZ NOT NULL,
    bid             NUMERIC(28, 12),
    bid_size        NUMERIC(28, 12),
    ask             NUMERIC(28, 12),
    ask_size        NUMERIC(28, 12),
    PRIMARY KEY (instrument_id, ts)
);

SELECT create_hypertable('quotes_l1', 'ts', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE bars (
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    resolution      TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    open            NUMERIC(28, 12) NOT NULL,
    high            NUMERIC(28, 12) NOT NULL,
    low             NUMERIC(28, 12) NOT NULL,
    close           NUMERIC(28, 12) NOT NULL,
    volume          NUMERIC(28, 12) NOT NULL,
    trade_count     INTEGER,
    vwap            NUMERIC(28, 12),
    PRIMARY KEY (instrument_id, resolution, ts)
);

SELECT create_hypertable('bars', 'ts', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_bars_inst_res_ts ON bars(instrument_id, resolution, ts DESC);

-- ============================================================
-- INGESTION HEALTH (also a hypertable)
-- ============================================================

CREATE TABLE ingestion_health (
    source              TEXT NOT NULL,
    instrument_id       BIGINT REFERENCES instruments(id),
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL,
    last_message_ts     TIMESTAMPTZ,
    message_count_1m    INTEGER,
    error_message       TEXT,
    PRIMARY KEY (source, instrument_id, ts)
);

SELECT create_hypertable('ingestion_health', 'ts', chunk_time_interval => INTERVAL '1 day');

-- ============================================================
-- SETTINGS (per-org defaults with per-user overrides)
-- ============================================================

CREATE TABLE settings_keys (
    key                 TEXT PRIMARY KEY,
    scope               TEXT NOT NULL,
    value_schema        JSONB NOT NULL,
    default_value       JSONB,
    description         TEXT NOT NULL,
    is_secret           BOOLEAN NOT NULL DEFAULT FALSE,
    category            TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_settings_keys_category ON settings_keys(category);
CREATE INDEX idx_settings_keys_scope ON settings_keys(scope);

CREATE TABLE org_settings (
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    setting_key         TEXT NOT NULL REFERENCES settings_keys(key),
    value               JSONB NOT NULL,
    updated_by          UUID REFERENCES users(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (org_id, setting_key)
);

CREATE INDEX idx_org_settings_key ON org_settings(setting_key);

CREATE TABLE user_settings (
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    setting_key         TEXT NOT NULL REFERENCES settings_keys(key),
    value               JSONB NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, setting_key)
);

CREATE INDEX idx_user_settings_key ON user_settings(setting_key);

-- ============================================================
-- AUDIT LOG (append-only by convention)
-- ============================================================

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         UUID REFERENCES users(id),
    org_id          UUID REFERENCES organizations(id),
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    resource_type   TEXT,
    resource_id     TEXT,
    payload         JSONB,
    result          TEXT,
    error_message   TEXT
);

CREATE INDEX idx_audit_user_ts ON audit_log(user_id, ts DESC);
CREATE INDEX idx_audit_action_ts ON audit_log(action, ts DESC);

-- ============================================================
-- SEED DATA
-- ============================================================

-- Default organization (single-tenant for Phase 1)
INSERT INTO organizations (id, name, plan_tier)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default Org', 'pro');

-- Phase 1 instruments
INSERT INTO instruments (asset_class, canonical_symbol, venue, native_symbol, base, quote)
VALUES
    ('crypto_spot', 'BTC-USDT@BINANCEUS', 'BINANCEUS', 'BTCUSDT', 'BTC', 'USDT'),
    ('crypto_spot', 'ETH-USDT@BINANCEUS', 'BINANCEUS', 'ETHUSDT', 'ETH', 'USDT');

-- Settings registry: definitions for every settings key the platform knows about.
-- Adding a new setting in a future phase is just an INSERT here.

INSERT INTO settings_keys (key, scope, value_schema, default_value, description, is_secret, category) VALUES
    ('profile.timezone', 'user',
     '{"type":"string","enum":["UTC","America/New_York","America/Los_Angeles","Europe/London","Asia/Singapore"]}'::jsonb,
     '"UTC"'::jsonb,
     'Display timezone for the user', false, 'profile'),

    ('profile.theme', 'user',
     '{"type":"string","enum":["dark","light","auto"]}'::jsonb,
     '"dark"'::jsonb,
     'UI theme preference', false, 'profile'),

    ('profile.default_chart_resolution', 'both',
     '{"type":"string","enum":["1m","5m","15m","1h","4h","1d"]}'::jsonb,
     '"1m"'::jsonb,
     'Default chart resolution (org default, user override allowed)', false, 'profile'),

    ('api_keys.binanceus.key', 'org',
     '{"type":"string"}'::jsonb,
     null,
     'Binance.US API key (encrypted at rest)', true, 'api_keys'),

    ('api_keys.binanceus.secret', 'org',
     '{"type":"string"}'::jsonb,
     null,
     'Binance.US API secret (encrypted at rest)', true, 'api_keys'),

    ('data.tracked_instruments', 'org',
     '{"type":"array","items":{"type":"string"}}'::jsonb,
     '["BTC-USDT@BINANCEUS","ETH-USDT@BINANCEUS"]'::jsonb,
     'List of canonical symbols to track via ingestion', false, 'data'),

    ('data.sources_enabled', 'org',
     '{"type":"object","additionalProperties":{"type":"boolean"}}'::jsonb,
     '{"binanceus":true,"alpaca":false}'::jsonb,
     'Which data sources are active', false, 'data');

-- ============================================================
-- Migration complete
-- ============================================================
