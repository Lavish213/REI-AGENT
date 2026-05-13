-- Batch D: Operational Orchestration Merge

-- workflows: append-only audit trail of all workflow state transitions
CREATE TABLE IF NOT EXISTS workflows (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  state text NOT NULL DEFAULT 'new_lead',
  previous_state text,
  trigger_source text DEFAULT 'system',
  triggered_by text,
  metadata jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflows_lead_id ON workflows(lead_id);
CREATE INDEX IF NOT EXISTS idx_workflows_state ON workflows(state);
CREATE INDEX IF NOT EXISTS idx_workflows_created_at ON workflows(created_at DESC);

-- followups: operational task queue for callbacks/follow-throughs
CREATE TABLE IF NOT EXISTS followups (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  call_id uuid REFERENCES calls(id) ON DELETE SET NULL,
  followup_type text NOT NULL DEFAULT 'call',
  priority text NOT NULL DEFAULT 'medium',
  state text NOT NULL DEFAULT 'pending',
  scheduled_at timestamptz,
  completed_at timestamptz,
  notes text,
  created_by text DEFAULT 'system',
  metadata jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_followups_lead_id ON followups(lead_id);
CREATE INDEX IF NOT EXISTS idx_followups_state_priority ON followups(state, priority);
CREATE INDEX IF NOT EXISTS idx_followups_scheduled ON followups(scheduled_at) WHERE state = 'pending';

-- leads: add operational workflow columns
ALTER TABLE leads ADD COLUMN IF NOT EXISTS workflow_state text DEFAULT 'new_lead';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS workflow_updated_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS escalated boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS operator_notes text;
