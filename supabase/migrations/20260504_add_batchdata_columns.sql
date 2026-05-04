ALTER TABLE properties
  ADD COLUMN IF NOT EXISTS batchrank_score integer,
  ADD COLUMN IF NOT EXISTS days_on_market integer,
  ADD COLUMN IF NOT EXISTS callable_phones jsonb,
  ADD COLUMN IF NOT EXISTS enriched_at timestamptz,
  ADD COLUMN IF NOT EXISTS nts_date text,
  ADD COLUMN IF NOT EXISTS years_owned numeric,
  ADD COLUMN IF NOT EXISTS pre_foreclosure boolean,
  ADD COLUMN IF NOT EXISTS absentee_owner boolean,
  ADD COLUMN IF NOT EXISTS owner_mailing_city text,
  ADD COLUMN IF NOT EXISTS owner_mailing_state text;

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS owner_phone text,
  ADD COLUMN IF NOT EXISTS owner_email text,
  ADD COLUMN IF NOT EXISTS callable boolean,
  ADD COLUMN IF NOT EXISTS dnc_blocked boolean;
