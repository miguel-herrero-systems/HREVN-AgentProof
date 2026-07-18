-- HREVN Start course persistence v1
-- Base PostgreSQL schema for real participant progress, attempts and completion.

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

CREATE TABLE IF NOT EXISTS hrevn_start_course_enrollments (
  enrollment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'created',
  full_name text NOT NULL,
  email citext NOT NULL,
  organization_name text NOT NULL,
  language text NOT NULL,
  role text,
  course_version text NOT NULL DEFAULT 'v1',
  optional_block_6_enabled boolean NOT NULL DEFAULT false,
  started_at timestamptz,
  completed_at timestamptz,
  last_seen_at timestamptz,
  current_block_code text,
  required_blocks_passed_count integer NOT NULL DEFAULT 0,
  required_course_completed boolean NOT NULL DEFAULT false,
  certificate_status text NOT NULL DEFAULT 'not_issued',
  source_path text,
  source_lead_id text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT hrevn_start_course_enrollments_full_name_not_blank
    CHECK (btrim(full_name) <> ''),
  CONSTRAINT hrevn_start_course_enrollments_email_not_blank
    CHECK (btrim(email::text) <> ''),
  CONSTRAINT hrevn_start_course_enrollments_org_name_not_blank
    CHECK (btrim(organization_name) <> ''),
  CONSTRAINT hrevn_start_course_enrollments_language_valid
    CHECK (language IN ('es', 'en')),
  CONSTRAINT hrevn_start_course_enrollments_status_valid
    CHECK (status IN ('created', 'in_progress', 'completed', 'abandoned', 'cancelled')),
  CONSTRAINT hrevn_start_course_enrollments_certificate_status_valid
    CHECK (certificate_status IN ('not_issued', 'queued', 'issued', 'failed', 'revoked')),
  CONSTRAINT hrevn_start_course_enrollments_current_block_code_valid
    CHECK (
      current_block_code IS NULL
      OR current_block_code IN ('block_1', 'block_2', 'block_3', 'block_4', 'block_5', 'block_6')
    ),
  CONSTRAINT hrevn_start_course_enrollments_required_blocks_passed_count_valid
    CHECK (required_blocks_passed_count >= 0 AND required_blocks_passed_count <= 5),
  CONSTRAINT hrevn_start_course_enrollments_completed_consistency
    CHECK (
      (required_course_completed = false)
      OR (required_course_completed = true AND completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_course_enrollments_course_email
  ON hrevn_start_course_enrollments (course_version, email);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_enrollments_status
  ON hrevn_start_course_enrollments (status);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_enrollments_org_name
  ON hrevn_start_course_enrollments (organization_name);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_enrollments_last_seen
  ON hrevn_start_course_enrollments (last_seen_at DESC NULLS LAST);

DROP TRIGGER IF EXISTS trg_hrevn_start_course_enrollments_updated_at ON hrevn_start_course_enrollments;
CREATE TRIGGER trg_hrevn_start_course_enrollments_updated_at
BEFORE UPDATE ON hrevn_start_course_enrollments
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

CREATE TABLE IF NOT EXISTS hrevn_start_course_block_attempts (
  attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES hrevn_start_course_enrollments (enrollment_id) ON DELETE CASCADE,
  block_code text NOT NULL,
  attempt_number integer NOT NULL,
  passed boolean NOT NULL,
  score integer NOT NULL,
  questions_presented jsonb NOT NULL DEFAULT '[]'::jsonb,
  answers_submitted jsonb NOT NULL DEFAULT '[]'::jsonb,
  result_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT hrevn_start_course_block_attempts_block_code_valid
    CHECK (block_code IN ('block_1', 'block_2', 'block_3', 'block_4', 'block_5', 'block_6')),
  CONSTRAINT hrevn_start_course_block_attempts_attempt_number_valid
    CHECK (attempt_number >= 1),
  CONSTRAINT hrevn_start_course_block_attempts_score_valid
    CHECK (score >= 0 AND score <= 5)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_course_block_attempts_enrollment_block_attempt
  ON hrevn_start_course_block_attempts (enrollment_id, block_code, attempt_number);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_block_attempts_enrollment_created_at
  ON hrevn_start_course_block_attempts (enrollment_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_block_attempts_block_code
  ON hrevn_start_course_block_attempts (block_code);

CREATE TABLE IF NOT EXISTS hrevn_start_course_block_status (
  block_status_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES hrevn_start_course_enrollments (enrollment_id) ON DELETE CASCADE,
  block_code text NOT NULL,
  passed boolean NOT NULL DEFAULT false,
  attempts_count integer NOT NULL DEFAULT 0,
  best_score integer,
  last_score integer,
  first_passed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT hrevn_start_course_block_status_block_code_valid
    CHECK (block_code IN ('block_1', 'block_2', 'block_3', 'block_4', 'block_5', 'block_6')),
  CONSTRAINT hrevn_start_course_block_status_attempts_count_valid
    CHECK (attempts_count >= 0),
  CONSTRAINT hrevn_start_course_block_status_best_score_valid
    CHECK (best_score IS NULL OR (best_score >= 0 AND best_score <= 5)),
  CONSTRAINT hrevn_start_course_block_status_last_score_valid
    CHECK (last_score IS NULL OR (last_score >= 0 AND last_score <= 5))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_hrevn_start_course_block_status_enrollment_block
  ON hrevn_start_course_block_status (enrollment_id, block_code);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_block_status_enrollment
  ON hrevn_start_course_block_status (enrollment_id);

DROP TRIGGER IF EXISTS trg_hrevn_start_course_block_status_updated_at ON hrevn_start_course_block_status;
CREATE TRIGGER trg_hrevn_start_course_block_status_updated_at
BEFORE UPDATE ON hrevn_start_course_block_status
FOR EACH ROW
EXECUTE FUNCTION hrevn_set_updated_at();

CREATE TABLE IF NOT EXISTS hrevn_start_course_activity_log (
  activity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES hrevn_start_course_enrollments (enrollment_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  event_type text NOT NULL,
  event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor_type text NOT NULL DEFAULT 'participant',
  CONSTRAINT hrevn_start_course_activity_log_event_type_not_blank
    CHECK (btrim(event_type) <> ''),
  CONSTRAINT hrevn_start_course_activity_log_actor_type_valid
    CHECK (actor_type IN ('participant', 'system', 'admin'))
);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_activity_log_enrollment_created_at
  ON hrevn_start_course_activity_log (enrollment_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_hrevn_start_course_activity_log_event_type
  ON hrevn_start_course_activity_log (event_type);

COMMIT;
