-- Batch C: Transcript + Intelligence Merge
-- transcript_chunks: structured per-utterance storage
CREATE TABLE IF NOT EXISTS transcript_chunks (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  call_id uuid REFERENCES calls(id) ON DELETE CASCADE,
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  speaker text NOT NULL,
  text text NOT NULL,
  chunk_type text NOT NULL DEFAULT 'final',
  sequence_order integer NOT NULL,
  confidence float,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transcript_chunks_call_id ON transcript_chunks(call_id);
CREATE INDEX IF NOT EXISTS idx_transcript_chunks_order ON transcript_chunks(call_id, sequence_order);
CREATE INDEX IF NOT EXISTS idx_transcript_chunks_lead_id ON transcript_chunks(lead_id);
CREATE INDEX IF NOT EXISTS idx_transcript_chunks_search ON transcript_chunks USING gin(to_tsvector('english', text));

-- call_events: canonical event log
CREATE TABLE IF NOT EXISTS call_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  call_id uuid REFERENCES calls(id) ON DELETE CASCADE,
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  payload jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_events_call_id ON call_events(call_id);
CREATE INDEX IF NOT EXISTS idx_call_events_event_type ON call_events(event_type);
CREATE INDEX IF NOT EXISTS idx_call_events_lead_id ON call_events(lead_id);

-- calls: add intel + linkage columns
ALTER TABLE calls ADD COLUMN IF NOT EXISTS property_id uuid REFERENCES properties(id) ON DELETE SET NULL;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_summary text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS seller_name text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS property_address_mentioned text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS asking_price bigint;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS occupancy text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS property_condition text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS distress_indicators jsonb DEFAULT '[]';
ALTER TABLE calls ADD COLUMN IF NOT EXISTS objections jsonb DEFAULT '[]';
ALTER TABLE calls ADD COLUMN IF NOT EXISTS appointment_interest boolean;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS next_step text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS followup_priority text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS extraction_confidence float;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS seller_motivation text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS motivation_confidence float;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS timeline text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS lead_score float;

-- leads: add derived intelligence columns
-- Fix: timeline_urgency was extracted but column was named timeline_mentioned
ALTER TABLE leads ADD COLUMN IF NOT EXISTS timeline_urgency text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS followup_urgency integer DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS conversation_quality float;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_hot_lead boolean DEFAULT false;
