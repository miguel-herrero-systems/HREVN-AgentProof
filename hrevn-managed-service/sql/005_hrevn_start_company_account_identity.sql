-- HREVN Start company account identity layer v1
-- Delta migration for company admin invites, magic links and auth sessions.

BEGIN;

UPDATE hrevn_start_company_admins
SET status = 'revoked'
WHERE status = 'disabled';

ALTER TABLE hrevn_start_company_admins
  DROP CONSTRAINT IF EXISTS hrevn_start_company_admins_status_valid;

ALTER TABLE hrevn_start_company_admins
  ADD CONSTRAINT hrevn_start_company_admins_status_valid
  CHECK (status IN ('invited', 'active', 'revoked', 'archived'));

CREATE TABLE IF NOT EXISTS hrevn_start_company_admin_invites (
  company_admin_invite_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  company_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE CASCADE,
  created_by_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  email citext NOT NULL,
  access_level text NOT NULL DEFAULT 'admin',
  token_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  revoked_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_company_admin_invites_access_level_valid
    CHECK (access_level IN ('owner', 'admin', 'viewer')),
  CONSTRAINT hrevn_start_company_admin_invites_email_not_blank
    CHECK (btrim(email::text) <> ''),
  CONSTRAINT hrevn_start_company_admin_invites_token_hash_not_blank
    CHECK (btrim(token_hash) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_company_admin_invites_token_hash
  ON hrevn_start_company_admin_invites (token_hash);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_admin_invites_company_email
  ON hrevn_start_company_admin_invites (company_id, email, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_admin_invites_admin
  ON hrevn_start_company_admin_invites (company_admin_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hrevn_start_auth_magic_links (
  auth_magic_link_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_admin_id uuid NOT NULL REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  token_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  revoked_at timestamptz,
  request_ip text,
  request_user_agent text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_auth_magic_links_token_hash_not_blank
    CHECK (btrim(token_hash) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_auth_magic_links_token_hash
  ON hrevn_start_auth_magic_links (token_hash);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_auth_magic_links_admin_created_at
  ON hrevn_start_auth_magic_links (company_admin_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hrevn_start_auth_sessions (
  auth_session_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_admin_id uuid NOT NULL REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  session_token_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  last_seen_at timestamptz,
  created_ip text,
  created_user_agent text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_auth_sessions_session_token_hash_not_blank
    CHECK (btrim(session_token_hash) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_auth_sessions_session_token_hash
  ON hrevn_start_auth_sessions (session_token_hash);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_auth_sessions_admin_created_at
  ON hrevn_start_auth_sessions (company_admin_id, created_at DESC);

COMMIT;
