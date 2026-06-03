-- Migration 0009: register settings keys for Polygon and the execution layer.
--
-- Additive and idempotent (ON CONFLICT DO NOTHING) so it can run on a populated
-- DB. Extends the settings registry seeded in 0001 with:
--   * Polygon API key (encrypted at rest)
--   * a Polygon toggle in the data-sources object
--   * a live-trading enablement flag mirrored in settings for UI visibility
--     (the authoritative kill-switch remains the BINANCEUS_LIVE_TRADING_ENABLED
--      env var read by the broker)

INSERT INTO settings_keys (key, scope, value_schema, default_value, description, is_secret, category)
VALUES
    ('api_keys.polygon.key', 'org',
     '{"type":"string"}'::jsonb,
     null,
     'Polygon.io API key (encrypted at rest)', true, 'api_keys'),

    ('trading.live_enabled', 'org',
     '{"type":"boolean"}'::jsonb,
     'false'::jsonb,
     'Whether live order transmission is permitted (mirrors BINANCEUS_LIVE_TRADING_ENABLED)',
     false, 'trading'),

    ('trading.default_paper_cash', 'org',
     '{"type":"number"}'::jsonb,
     '100000'::jsonb,
     'Starting cash for newly-created paper trading accounts', false, 'trading')
ON CONFLICT (key) DO NOTHING;

-- Refresh the default data-sources object to include polygon. Only updates the
-- org-level default if it is still the original two-source value, so we don't
-- clobber an operator's customized selection.
UPDATE settings_keys
SET default_value = '{"binanceus":true,"alpaca":false,"polygon":false}'::jsonb
WHERE key = 'data.sources_enabled'
  AND default_value = '{"binanceus":true,"alpaca":false}'::jsonb;
