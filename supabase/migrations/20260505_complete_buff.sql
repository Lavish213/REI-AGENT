ALTER TABLE leads ADD COLUMN IF NOT EXISTS speed_to_lead_started_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS engagement_score integer DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_opted_out boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_email text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS voicemail_callback boolean DEFAULT false;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS voicemail_script_version integer;
