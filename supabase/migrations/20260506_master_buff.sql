ALTER TABLE properties ADD COLUMN IF NOT EXISTS move_score integer DEFAULT 0;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS walk_score integer;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS transit_score integer;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS median_household_income integer;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS vacancy_rate float;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS owner_occupancy_rate float;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS social_source text;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS social_post_url text;

ALTER TABLE leads ADD COLUMN IF NOT EXISTS call_summaries jsonb DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS price_floor bigint;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS hot_topics jsonb DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rapport_openers jsonb DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS objections_raised jsonb DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS competitor_mentions jsonb DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS timeline_mentioned text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS motivation_level integer;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS best_callback_time text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_best_action text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS birthday date;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS wedding_anniversary date;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS home_purchase_anniversary date;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS spouse_name text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS spouse_phone text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS move_score integer DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_sms boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_method text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS dnc_blocked boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS engagement_score integer DEFAULT 0;

CREATE TABLE IF NOT EXISTS compliance_log (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  event_type text NOT NULL,
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  timestamp timestamptz DEFAULT now(),
  details jsonb,
  outcome text,
  blocked_reason text
);
