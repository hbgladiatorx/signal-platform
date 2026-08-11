-- 0025_paper_session_heartbeat.sql
-- ============================================================
-- Liveness heartbeat for paper/live sessions.
--
-- A session's `status` says what it SHOULD be doing, but not whether a worker is
-- actually executing it. The paper_trader now stamps `last_heartbeat_at` for
-- every session it owns, on a fixed cadence independent of market hours. The UI
-- compares it to now(): a 'running' session with a stale (or missing) heartbeat
-- is surfaced as "no worker" instead of silently looking healthy — the failure
-- mode where a session's row outlived the process running it.
--
-- Idempotent: safe to run more than once.
-- ============================================================

ALTER TABLE paper_sessions
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
