-- HREVN Start policy persistence v1
-- Base PostgreSQL schema for policy questionnaire submissions, derived context and generated policy documents.

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

CREATE TABLE IF NOT EXISTS hrevn_start_policy_cases (
  policy_case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'created',
  organization_legal_name text NOT NULL,
  organization_tax_id text NOT NULL,
  sector_label text NOT NULL,
  workforce_range text NOT NULL,
  representative_name text NOT NULL,
  representative_role text NOT NULL,
  representative_email citext NOT NULL,
  country_scope text NOT NULL,
  policy_language text NOT NULL DEFAULT 'es',
  source_page text NOT NULL DEFAULT 'chequeo-uso-ia-politica',
  source_lead_id text,
  latest_scope_result text,
  latest_submission_id uuid,
  current_policy_document_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_policy_cases_status_valid
    CHECK (status IN ('created', 'questionnaire_in_progress', 'questionnaire_submitted', 'policy_generated', 'policy_reviewed', 'policy_issued', 'archived')),
  CONSTRAINT hrevn_start_policy_cases_org_name_not_blank
    CHECK (btrim(organization_legal_name) <> ''),
  CONSTRAINT hrevn_start_policy_cases_org_tax_id_not_blank
    CHECK (btrim(organization_tax_id) <> ''),
  CONSTRAINT hrevn_start_policy_cases_sector_not_blank
    CHECK (btrim(sector_label) <> ''),
  CONSTRAINT hrevn_start_policy_cases_workforce_range_valid
    CHECK (workforce_range IN ('1_5', '6_10', '11_50', '51_250', '250_plus')),
  CONSTRAINT hrevn_start_policy_cases_representative_name_not_blank
    CHECK (btrim(representative_name) <> ''),
  CONSTRAINT hrevn_start_policy_cases_representative_role_not_blank
    CHECK (btrim(representative_role) <> ''),
  CONSTRAINT hrevn_start_policy_cases_representative_email_not_blank
    CHECK (btrim(representative_email::text) <> ''),
  CONSTRAINT hrevn_start_policy_cases_country_scope_not_blank
    CHECK (btrim(country_scope) <> ''),
  CONSTRAINT hrevn_start_policy_cases_policy_language_valid
    CHECK (policy_language IN ('es', 'en', 'both')),
  CONSTRAINT hrevn_start_policy_cases_latest_scope_result_valid
    CHECK (
      latest_scope_result IS NULL
      OR latest_scope_result IN ('start_basic', 'start_reinforced', 'outside_start_review')
    )
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_cases_status
  ON hrevn_start_policy_cases (status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_cases_org_tax_id
  ON hrevn_start_policy_cases (organization_tax_id);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_cases_representative_email
  ON hrevn_start_policy_cases (representative_email);

DROP TRIGGER IF EXISTS trg_hrevn_start_policy_cases_updated_at ON hrevn_start_policy_cases;
CREATE TRIGGER trg_hrevn_start_policy_cases_updated_at
BEFORE UPDATE ON hrevn_start_policy_cases
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

CREATE TABLE IF NOT EXISTS hrevn_start_policy_questionnaire_submissions (
  submission_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_case_id uuid NOT NULL REFERENCES hrevn_start_policy_cases (policy_case_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  questionnaire_id text NOT NULL DEFAULT 'hrevn_start_policy_questionnaire',
  questionnaire_version text NOT NULL DEFAULT 'v1',
  language text NOT NULL DEFAULT 'es',
  source_page text NOT NULL DEFAULT 'chequeo-uso-ia-politica',
  page_url text,
  user_agent text,
  ip_address inet,
  answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  normalized_answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_document_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_render_plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_risk_signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  scope_result text NOT NULL,
  representative_declaration_confirmed boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_policy_questionnaire_submissions_questionnaire_id_not_blank
    CHECK (btrim(questionnaire_id) <> ''),
  CONSTRAINT hrevn_start_policy_questionnaire_submissions_questionnaire_version_not_blank
    CHECK (btrim(questionnaire_version) <> ''),
  CONSTRAINT hrevn_start_policy_questionnaire_submissions_language_valid
    CHECK (language IN ('es', 'en')),
  CONSTRAINT hrevn_start_policy_questionnaire_submissions_scope_result_valid
    CHECK (scope_result IN ('start_basic', 'start_reinforced', 'outside_start_review'))
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_questionnaire_submissions_case_submitted_at
  ON hrevn_start_policy_questionnaire_submissions (policy_case_id, submitted_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_questionnaire_submissions_scope_result
  ON hrevn_start_policy_questionnaire_submissions (scope_result);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_questionnaire_submissions_questionnaire_version
  ON hrevn_start_policy_questionnaire_submissions (questionnaire_version);

CREATE TABLE IF NOT EXISTS hrevn_start_policy_documents (
  policy_document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_case_id uuid NOT NULL REFERENCES hrevn_start_policy_cases (policy_case_id) ON DELETE CASCADE,
  source_submission_id uuid REFERENCES hrevn_start_policy_questionnaire_submissions (submission_id) ON DELETE SET NULL,
  supersedes_document_id uuid REFERENCES hrevn_start_policy_documents (policy_document_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  issued_at timestamptz,
  language text NOT NULL DEFAULT 'es',
  policy_version text NOT NULL DEFAULT 'v1.0',
  document_kind text NOT NULL DEFAULT 'policy_internal',
  status text NOT NULL DEFAULT 'draft',
  scope_result text NOT NULL,
  title text NOT NULL DEFAULT 'Politica interna de uso responsable de inteligencia artificial',
  context_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  render_plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  rendered_content jsonb NOT NULL DEFAULT '{}'::jsonb,
  storage_path text,
  sha256 text,
  artifact_id text,
  verification_code text,
  verification_url text,
  anchor_network text,
  anchor_status text,
  anchor_method text,
  anchor_transaction_reference text,
  anchored_at timestamptz,
  anchor_error text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_policy_documents_language_valid
    CHECK (language IN ('es', 'en')),
  CONSTRAINT hrevn_start_policy_documents_policy_version_not_blank
    CHECK (btrim(policy_version) <> ''),
  CONSTRAINT hrevn_start_policy_documents_document_kind_valid
    CHECK (document_kind IN ('policy_internal', 'policy_record')),
  CONSTRAINT hrevn_start_policy_documents_status_valid
    CHECK (status IN ('draft', 'generated', 'reviewed', 'issued', 'superseded', 'failed', 'revoked')),
  CONSTRAINT hrevn_start_policy_documents_scope_result_valid
    CHECK (scope_result IN ('start_basic', 'start_reinforced', 'outside_start_review')),
  CONSTRAINT hrevn_start_policy_documents_anchor_status_valid
    CHECK (
      anchor_status IS NULL
      OR anchor_status IN ('anchored', 'anchor_pending', 'anchor_failed')
    ),
  CONSTRAINT hrevn_start_policy_documents_title_not_blank
    CHECK (btrim(title) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_policy_documents_case_kind_language_version
  ON hrevn_start_policy_documents (policy_case_id, document_kind, language, policy_version);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_documents_case_created_at
  ON hrevn_start_policy_documents (policy_case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_documents_status
  ON hrevn_start_policy_documents (status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_documents_artifact_id
  ON hrevn_start_policy_documents (artifact_id);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_documents_anchor_status
  ON hrevn_start_policy_documents (anchor_status);

DROP TRIGGER IF EXISTS trg_hrevn_start_policy_documents_updated_at ON hrevn_start_policy_documents;
CREATE TRIGGER trg_hrevn_start_policy_documents_updated_at
BEFORE UPDATE ON hrevn_start_policy_documents
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

ALTER TABLE hrevn_start_policy_cases
  DROP CONSTRAINT IF EXISTS fk_hrevn_start_policy_cases_latest_submission_id;

ALTER TABLE hrevn_start_policy_cases
  ADD CONSTRAINT fk_hrevn_start_policy_cases_latest_submission_id
  FOREIGN KEY (latest_submission_id)
  REFERENCES hrevn_start_policy_questionnaire_submissions (submission_id)
  ON DELETE SET NULL;

ALTER TABLE hrevn_start_policy_cases
  DROP CONSTRAINT IF EXISTS fk_hrevn_start_policy_cases_current_policy_document_id;

ALTER TABLE hrevn_start_policy_cases
  ADD CONSTRAINT fk_hrevn_start_policy_cases_current_policy_document_id
  FOREIGN KEY (current_policy_document_id)
  REFERENCES hrevn_start_policy_documents (policy_document_id)
  ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS hrevn_start_policy_activity_log (
  activity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_case_id uuid NOT NULL REFERENCES hrevn_start_policy_cases (policy_case_id) ON DELETE CASCADE,
  submission_id uuid REFERENCES hrevn_start_policy_questionnaire_submissions (submission_id) ON DELETE SET NULL,
  policy_document_id uuid REFERENCES hrevn_start_policy_documents (policy_document_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  event_type text NOT NULL,
  event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor_type text NOT NULL DEFAULT 'representative',
  CONSTRAINT hrevn_start_policy_activity_log_event_type_not_blank
    CHECK (btrim(event_type) <> ''),
  CONSTRAINT hrevn_start_policy_activity_log_actor_type_valid
    CHECK (actor_type IN ('representative', 'system', 'admin'))
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_activity_log_case_created_at
  ON hrevn_start_policy_activity_log (policy_case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_activity_log_event_type
  ON hrevn_start_policy_activity_log (event_type);

COMMIT;
