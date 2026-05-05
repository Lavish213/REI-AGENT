ALTER TABLE calls
  ADD COLUMN IF NOT EXISTS call_disposition text;

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS priority_callback boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS appointment_at timestamptz,
  ADD COLUMN IF NOT EXISTS appt_day_before_sent boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS appt_morning_sent boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS appt_no_show_sent boolean DEFAULT false;
