-- 0015_user_prefs_json.sql
-- ============================================================
-- Add a free-form JSONB preferences blob to user_preferences.
--
-- The typed columns (timezone, theme, notifications_enabled) cover the
-- backend's own settings surface. The thebayn frontend additionally keeps
-- an arbitrary client-owned preferences bag (onboarding flags, asset-class
-- filters, UI layout choices, etc.) that previously lived in a Supabase
-- `user_preferences.prefs` JSONB. This column is its new home, served by
-- GET/PUT /settings/preferences.
--
-- Idempotent: safe to re-run.
-- ============================================================

ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb;
