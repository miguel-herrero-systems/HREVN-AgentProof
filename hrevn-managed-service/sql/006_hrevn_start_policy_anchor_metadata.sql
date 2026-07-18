BEGIN;

ALTER TABLE hrevn_start_policy_documents
  ADD COLUMN IF NOT EXISTS anchor_network text,
  ADD COLUMN IF NOT EXISTS anchor_status text,
  ADD COLUMN IF NOT EXISTS anchor_method text,
  ADD COLUMN IF NOT EXISTS anchor_transaction_reference text,
  ADD COLUMN IF NOT EXISTS anchored_at timestamptz,
  ADD COLUMN IF NOT EXISTS anchor_error text;

ALTER TABLE hrevn_start_policy_documents
  DROP CONSTRAINT IF EXISTS hrevn_start_policy_documents_anchor_status_valid;

ALTER TABLE hrevn_start_policy_documents
  ADD CONSTRAINT hrevn_start_policy_documents_anchor_status_valid
  CHECK (
    anchor_status IS NULL
    OR anchor_status IN ('anchored', 'anchor_pending', 'anchor_failed')
  );

CREATE INDEX IF NOT EXISTS ix_hrevn_start_policy_documents_anchor_status
  ON hrevn_start_policy_documents (anchor_status);

COMMIT;
