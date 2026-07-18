-- HREVN Start company training layer v1
-- Base PostgreSQL schema for company admins, training groups, invited participants and evidence exports.

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION hrevn_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS hrevn_start_companies (
  company_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'created',
  legal_name text NOT NULL,
  tax_id text NOT NULL,
  display_name text,
  contact_email citext NOT NULL,
  country_scope text NOT NULL DEFAULT 'spain',
  workforce_range text NOT NULL DEFAULT '1_5',
  current_policy_case_id uuid REFERENCES hrevn_start_policy_cases (policy_case_id) ON DELETE SET NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_companies_status_valid
    CHECK (status IN ('created', 'active', 'archived')),
  CONSTRAINT hrevn_start_companies_legal_name_not_blank
    CHECK (btrim(legal_name) <> ''),
  CONSTRAINT hrevn_start_companies_tax_id_not_blank
    CHECK (btrim(tax_id) <> ''),
  CONSTRAINT hrevn_start_companies_contact_email_not_blank
    CHECK (btrim(contact_email::text) <> ''),
  CONSTRAINT hrevn_start_companies_country_scope_not_blank
    CHECK (btrim(country_scope) <> ''),
  CONSTRAINT hrevn_start_companies_workforce_range_valid
    CHECK (workforce_range IN ('1_5', '6_10', '11_50', '51_250', '250_plus'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_companies_tax_id
  ON hrevn_start_companies (tax_id);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_companies_status
  ON hrevn_start_companies (status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_companies_contact_email
  ON hrevn_start_companies (contact_email);

DROP TRIGGER IF EXISTS trg_hrevn_start_companies_updated_at ON hrevn_start_companies;
CREATE TRIGGER trg_hrevn_start_companies_updated_at
BEFORE UPDATE ON hrevn_start_companies
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

CREATE TABLE IF NOT EXISTS hrevn_start_company_admins (
  company_admin_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'invited',
  access_level text NOT NULL DEFAULT 'admin',
  full_name text NOT NULL,
  email citext NOT NULL,
  job_title text,
  invited_at timestamptz,
  accepted_at timestamptz,
  last_seen_at timestamptz,
  last_login_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_company_admins_status_valid
    CHECK (status IN ('invited', 'active', 'revoked', 'archived')),
  CONSTRAINT hrevn_start_company_admins_access_level_valid
    CHECK (access_level IN ('owner', 'admin', 'viewer')),
  CONSTRAINT hrevn_start_company_admins_full_name_not_blank
    CHECK (btrim(full_name) <> ''),
  CONSTRAINT hrevn_start_company_admins_email_not_blank
    CHECK (btrim(email::text) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_company_admins_company_email
  ON hrevn_start_company_admins (company_id, email);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_admins_company_status
  ON hrevn_start_company_admins (company_id, status);

DROP TRIGGER IF EXISTS trg_hrevn_start_company_admins_updated_at ON hrevn_start_company_admins;
CREATE TRIGGER trg_hrevn_start_company_admins_updated_at
BEFORE UPDATE ON hrevn_start_company_admins
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

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

CREATE TABLE IF NOT EXISTS hrevn_start_training_groups (
  training_group_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  created_by_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE SET NULL,
  policy_case_id uuid REFERENCES hrevn_start_policy_cases (policy_case_id) ON DELETE SET NULL,
  policy_document_id uuid REFERENCES hrevn_start_policy_documents (policy_document_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'draft',
  title text NOT NULL,
  description text,
  course_version text NOT NULL DEFAULT 'v1',
  default_language text NOT NULL DEFAULT 'es',
  planned_start_date date,
  planned_end_date date,
  launched_at timestamptz,
  closed_at timestamptz,
  participant_count integer NOT NULL DEFAULT 0,
  completed_count integer NOT NULL DEFAULT 0,
  certificate_issued_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_training_groups_status_valid
    CHECK (status IN ('draft', 'inviting', 'in_progress', 'completed', 'archived', 'cancelled')),
  CONSTRAINT hrevn_start_training_groups_title_not_blank
    CHECK (btrim(title) <> ''),
  CONSTRAINT hrevn_start_training_groups_default_language_valid
    CHECK (default_language IN ('es', 'en', 'both')),
  CONSTRAINT hrevn_start_training_groups_participant_count_valid
    CHECK (participant_count >= 0),
  CONSTRAINT hrevn_start_training_groups_completed_count_valid
    CHECK (completed_count >= 0),
  CONSTRAINT hrevn_start_training_groups_certificate_count_valid
    CHECK (certificate_issued_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_training_groups_company_status
  ON hrevn_start_training_groups (company_id, status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_training_groups_company_created_at
  ON hrevn_start_training_groups (company_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_hrevn_start_training_groups_updated_at ON hrevn_start_training_groups;
CREATE TRIGGER trg_hrevn_start_training_groups_updated_at
BEFORE UPDATE ON hrevn_start_training_groups
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

CREATE TABLE IF NOT EXISTS hrevn_start_company_participants (
  company_participant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  training_group_id uuid NOT NULL REFERENCES hrevn_start_training_groups (training_group_id) ON DELETE CASCADE,
  invited_by_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE SET NULL,
  course_enrollment_id uuid REFERENCES hrevn_start_course_enrollments (enrollment_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'invited',
  full_name text NOT NULL,
  email citext NOT NULL,
  role text,
  language text NOT NULL DEFAULT 'es',
  employee_reference text,
  invite_token text NOT NULL,
  invited_at timestamptz,
  opened_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  certificate_issued_at timestamptz,
  last_seen_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_company_participants_status_valid
    CHECK (status IN ('invited', 'opened', 'in_progress', 'completed', 'certificate_issued', 'cancelled', 'bounced')),
  CONSTRAINT hrevn_start_company_participants_full_name_not_blank
    CHECK (btrim(full_name) <> ''),
  CONSTRAINT hrevn_start_company_participants_email_not_blank
    CHECK (btrim(email::text) <> ''),
  CONSTRAINT hrevn_start_company_participants_language_valid
    CHECK (language IN ('es', 'en')),
  CONSTRAINT hrevn_start_company_participants_invite_token_not_blank
    CHECK (btrim(invite_token) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_company_participants_group_email
  ON hrevn_start_company_participants (training_group_id, email);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_company_participants_invite_token
  ON hrevn_start_company_participants (invite_token);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_company_participants_enrollment
  ON hrevn_start_company_participants (course_enrollment_id)
  WHERE course_enrollment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_participants_group_status
  ON hrevn_start_company_participants (training_group_id, status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_participants_company_created_at
  ON hrevn_start_company_participants (company_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_hrevn_start_company_participants_updated_at ON hrevn_start_company_participants;
CREATE TRIGGER trg_hrevn_start_company_participants_updated_at
BEFORE UPDATE ON hrevn_start_company_participants
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

ALTER TABLE hrevn_start_course_enrollments
  ADD COLUMN IF NOT EXISTS company_id uuid REFERENCES hrevn_start_companies (company_id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS training_group_id uuid REFERENCES hrevn_start_training_groups (training_group_id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS company_participant_id uuid REFERENCES hrevn_start_company_participants (company_participant_id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS enrollment_origin text NOT NULL DEFAULT 'self_serve';

ALTER TABLE hrevn_start_course_enrollments
  DROP CONSTRAINT IF EXISTS hrevn_start_course_enrollments_enrollment_origin_valid;

ALTER TABLE hrevn_start_course_enrollments
  ADD CONSTRAINT hrevn_start_course_enrollments_enrollment_origin_valid
  CHECK (enrollment_origin IN ('self_serve', 'company_invite', 'admin_created'));

DROP INDEX IF EXISTS ux_hrevn_start_course_enrollments_course_email;

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_course_enrollments_legacy_course_email
  ON hrevn_start_course_enrollments (course_version, email)
  WHERE company_participant_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_course_enrollments_company_participant
  ON hrevn_start_course_enrollments (company_participant_id)
  WHERE company_participant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_enrollments_company
  ON hrevn_start_course_enrollments (company_id);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_enrollments_training_group
  ON hrevn_start_course_enrollments (training_group_id);

CREATE TABLE IF NOT EXISTS hrevn_start_training_group_exports (
  training_group_export_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  training_group_id uuid NOT NULL REFERENCES hrevn_start_training_groups (training_group_id) ON DELETE CASCADE,
  requested_by_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  generated_at timestamptz,
  expires_at timestamptz,
  export_kind text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  file_name text,
  storage_path text,
  sha256 text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_training_group_exports_export_kind_valid
    CHECK (export_kind IN ('participants_csv', 'certificates_zip', 'completion_report', 'evidence_bundle')),
  CONSTRAINT hrevn_start_training_group_exports_status_valid
    CHECK (status IN ('queued', 'generated', 'failed', 'expired'))
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_training_group_exports_group_created_at
  ON hrevn_start_training_group_exports (training_group_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_training_group_exports_status
  ON hrevn_start_training_group_exports (status);

CREATE TABLE IF NOT EXISTS hrevn_start_company_activity_log (
  company_activity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES hrevn_start_companies (company_id) ON DELETE CASCADE,
  training_group_id uuid REFERENCES hrevn_start_training_groups (training_group_id) ON DELETE SET NULL,
  company_participant_id uuid REFERENCES hrevn_start_company_participants (company_participant_id) ON DELETE SET NULL,
  company_admin_id uuid REFERENCES hrevn_start_company_admins (company_admin_id) ON DELETE SET NULL,
  course_enrollment_id uuid REFERENCES hrevn_start_course_enrollments (enrollment_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  event_type text NOT NULL,
  event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor_type text NOT NULL DEFAULT 'system',
  CONSTRAINT hrevn_start_company_activity_log_event_type_not_blank
    CHECK (btrim(event_type) <> ''),
  CONSTRAINT hrevn_start_company_activity_log_actor_type_valid
    CHECK (actor_type IN ('company_admin', 'participant', 'system'))
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_activity_log_company_created_at
  ON hrevn_start_company_activity_log (company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_activity_log_participant_created_at
  ON hrevn_start_company_activity_log (company_participant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_company_activity_log_event_type
  ON hrevn_start_company_activity_log (event_type);

COMMIT;
