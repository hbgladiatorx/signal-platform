-- 0024_mark_internal_accounts_system.sql
-- ============================================================
-- Hide internal QA / audit accounts from the admin user list.
--
-- The flow-audit e2e probe (and any @cimcha.io internal account) is not a real
-- user. The admin console excludes role='system' from the user list and all
-- human-facing counts, so pin these accounts to 'system'. Going forward,
-- deps.provision_user_record re-applies this on every authentication, so even if
-- such an account keeps re-authing it never reappears as a 'member'.
--
-- Idempotent.
-- ============================================================
UPDATE users
   SET role = 'system', updated_at = NOW()
 WHERE role <> 'system'
   AND (lower(email) LIKE 'flow-audit%' OR lower(email) LIKE '%@cimcha.io');
