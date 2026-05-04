ALTER TABLE properties
  ADD COLUMN IF NOT EXISTS land_use text,
  ADD COLUMN IF NOT EXISTS ownership_months integer,
  ADD COLUMN IF NOT EXISTS owner_type text,
  ADD COLUMN IF NOT EXISTS estimated_equity bigint,
  ADD COLUMN IF NOT EXISTS last_sale_date text,
  ADD COLUMN IF NOT EXISTS last_sale_amount bigint,
  ADD COLUMN IF NOT EXISTS tax_amount bigint,
  ADD COLUMN IF NOT EXISTS market_value bigint,
  ADD COLUMN IF NOT EXISTS default_amount bigint,
  ADD COLUMN IF NOT EXISTS opening_bid bigint;
