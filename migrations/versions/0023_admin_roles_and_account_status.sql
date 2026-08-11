-- 0023_admin_roles_and_account_status.sql
-- ============================================================
-- Admin tier + account activation status.
--
-- Roles: the `users.role` column already exists (default 'member'; the internal
-- platform account is 'system'). This migration introduces 'admin' as a real,
-- enforced role and adds a per-account `is_active` flag so an admin can disable
-- an account without deleting it (a disabled user is rejected at auth time).
--
-- Idempotent: safe to run more than once.
-- ============================================================

-- Soft-disable switch. Default TRUE so every existing account stays active.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- Fast lookups for the admin user list (ordered by signup) and role filters.
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);

COMMENT ON COLUMN users.is_active IS
    'FALSE = account disabled by an admin; rejected at authentication (403).';
COMMENT ON COLUMN users.role IS
    'member (default) | admin (elevated) | system (internal platform account).';
