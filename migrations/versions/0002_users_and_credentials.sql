-- Step 13: user identity and encrypted credential storage
--
-- New tables:
--   users               — one row per Auth0 sub (the platform's identity table)
--   user_preferences    — per-user preferences (theme, timezone, etc.)
--   api_credentials     — encrypted external-service credentials
--
-- All FKs cascade so deleting a user cleans up their preferences and credentials.

-- ============================================================
-- users
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES orgs(id)
                DEFAULT '00000000-0000-0000-0000-000000000001',
    auth0_sub   TEXT NOT NULL UNIQUE,
    email       TEXT,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_auth0_sub ON users(auth0_sub);
CREATE INDEX IF NOT EXISTS idx_users_org_id    ON users(org_id);


-- ============================================================
-- user_preferences
-- ============================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id               UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    timezone              TEXT NOT NULL DEFAULT 'UTC',
    theme                 TEXT NOT NULL DEFAULT 'light'
                          CHECK (theme IN ('light','dark','system')),
    notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- api_credentials
-- encrypted_payload is a Fernet token (base64-encoded ciphertext+HMAC).
-- ============================================================
CREATE TABLE IF NOT EXISTS api_credentials (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service            TEXT NOT NULL,
    label              TEXT NOT NULL,
    encrypted_payload  BYTEA NOT NULL,
    last_four          TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at       TIMESTAMPTZ,
    -- A user can't have two credentials for the same service with the same label,
    -- but they can have multiple credentials for the same service if labeled differently.
    UNIQUE (user_id, service, label)
);

CREATE INDEX IF NOT EXISTS idx_api_credentials_user
    ON api_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_api_credentials_service
    ON api_credentials(service);
