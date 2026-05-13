-- Batch E: MVP Demo + Operator Productization

-- offers: track offer drafts and status through negotiation lifecycle
CREATE TABLE IF NOT EXISTS offers (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  property_id uuid REFERENCES properties(id) ON DELETE SET NULL,
  arv_used bigint,                        -- cents: ARV used for this offer
  repair_estimate bigint DEFAULT 2500000, -- cents: default $25k repair buffer
  mao_calculated bigint,                  -- cents: (arv_used * 0.70) - repair_estimate
  offer_amount bigint,                    -- cents: operator-set final offer (may differ from MAO)
  offer_status text DEFAULT 'draft',      -- draft / sent / countered / accepted / rejected / expired
  notes text,
  created_by text DEFAULT 'operator',
  metadata jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_offers_lead_id ON offers(lead_id);
CREATE INDEX IF NOT EXISTS idx_offers_property_id ON offers(property_id);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(offer_status);
CREATE INDEX IF NOT EXISTS idx_offers_created_at ON offers(created_at DESC);

-- leads: walkthrough tracking columns
ALTER TABLE leads ADD COLUMN IF NOT EXISTS walkthrough_state text DEFAULT 'none';
  -- none / scheduled / completed / missed / cancelled
ALTER TABLE leads ADD COLUMN IF NOT EXISTS walkthrough_notes text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS walkthrough_completed_at timestamptz;
