ALTER TABLE properties ADD COLUMN IF NOT EXISTS price_reduced boolean DEFAULT false;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS last_list_price bigint;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS days_on_market integer;
