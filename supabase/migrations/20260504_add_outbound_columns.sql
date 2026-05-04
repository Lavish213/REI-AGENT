ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS last_called_at timestamptz,
  ADD COLUMN IF NOT EXISTS call_attempts integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_call_outcome text,
  ADD COLUMN IF NOT EXISTS callback_scheduled_at timestamptz;
