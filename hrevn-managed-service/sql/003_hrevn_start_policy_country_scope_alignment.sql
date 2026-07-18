BEGIN;

ALTER TABLE public.hrevn_start_policy_cases
  ADD COLUMN IF NOT EXISTS country_scope text;

UPDATE public.hrevn_start_policy_cases
SET country_scope = 'spain'
WHERE country_scope IS NULL OR btrim(country_scope) = '';

ALTER TABLE public.hrevn_start_policy_cases
  ALTER COLUMN country_scope SET NOT NULL;

ALTER TABLE public.hrevn_start_policy_cases
  DROP CONSTRAINT IF EXISTS hrevn_start_policy_cases_country_scope_not_blank;

ALTER TABLE public.hrevn_start_policy_cases
  ADD CONSTRAINT hrevn_start_policy_cases_country_scope_not_blank
  CHECK (btrim(country_scope) <> '');

COMMIT;
