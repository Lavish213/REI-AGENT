ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS drip_sequence text DEFAULT 'seller',
  ADD COLUMN IF NOT EXISTS drip_day integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS drip_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS drip_paused boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS drip_completed boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS last_sms_at timestamptz,
  ADD COLUMN IF NOT EXISTS opted_out boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS drip_replies jsonb DEFAULT '[]';
