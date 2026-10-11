-- Gate 1A step 1: persist tenant ownership, and step 2: suppression evidence.
--
-- Only 6 of the 28 tables this application references are created by committed
-- migrations. Every ALTER below is therefore written defensively so it applies
-- cleanly whether or not the target table exists in a given environment.
-- Reconstructing the missing 22 table definitions is Gate 1A step 5 and is NOT
-- attempted here.

CREATE TABLE IF NOT EXISTS tenants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        text NOT NULL UNIQUE,
  legal_name  text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO tenants (id, slug, legal_name)
VALUES ('00000000-0000-0000-0000-000000000001',
        'san-joaquin-house-buyers',
        'San Joaquin House Buyers')
ON CONFLICT (id) DO NOTHING;

-- Add, backfill, constrain and index tenant_id on every business table.
-- Backfill targets the single existing tenant. If this database ever held more
-- than one operator's data, STOP and do not run this migration.
DO $$
DECLARE
  t            text;
  default_uuid constant uuid := '00000000-0000-0000-0000-000000000001';
  business_tables constant text[] := ARRAY[
    'leads', 'properties', 'calls', 'contacts', 'comps', 'offers',
    'sms_messages', 'email_sends', 'email_events', 'followups', 'campaigns',
    'deal_blast_sends', 'phone_pool_health', 'dnc_list', 'cash_buyers',
    'intel_packets', 'packet_events', 'decision_records', 'bob_feedback_events',
    'transcript_chunks', 'call_events', 'approval_requests', 'operator_queries',
    'tool_gate_log', 'workflows', 'traces', 'eval_runs', 'latency_benchmarks',
    'compliance_log'
  ];
BEGIN
  FOREACH t IN ARRAY business_tables LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE 'skipping % — table not present in this database', t;
      CONTINUE;
    END IF;

    EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS tenant_id uuid', t);
    EXECUTE format('UPDATE public.%I SET tenant_id = %L WHERE tenant_id IS NULL', t, default_uuid);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET DEFAULT %L', t, default_uuid);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET NOT NULL', t);

    BEGIN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (tenant_id) REFERENCES public.tenants(id)',
        t, t || '_tenant_id_fkey'
      );
    EXCEPTION WHEN duplicate_object THEN
      NULL;
    END;

    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON public.%I (tenant_id)', 'idx_' || t || '_tenant', t);

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_tenant_isolation', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I USING (tenant_id::text = current_setting(''app.tenant_id'', true))',
      t || '_tenant_isolation', t
    );
  END LOOP;
END $$;

-- Append-only suppression evidence. One row per STOP/DNC/opt-out event.
-- Nothing in this table is ever updated or deleted: a later re-opt-in is a new
-- row with action = 'granted', never a mutation of the row that revoked.
CREATE TABLE IF NOT EXISTS suppression_events (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                 REFERENCES tenants(id),
  lead_id        uuid,
  contact_point  text NOT NULL,
  contact_type   text NOT NULL DEFAULT 'phone',
  channel        text NOT NULL DEFAULT 'all',
  action         text NOT NULL DEFAULT 'suppressed',
  reason         text,
  method         text NOT NULL,
  source         text NOT NULL,
  call_sid       text,
  verbatim       text,
  actor          text NOT NULL DEFAULT 'system',
  occurred_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_suppression_contact ON suppression_events (contact_point);
CREATE INDEX IF NOT EXISTS idx_suppression_lead ON suppression_events (lead_id);
CREATE INDEX IF NOT EXISTS idx_suppression_tenant ON suppression_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_suppression_occurred ON suppression_events (occurred_at DESC);

ALTER TABLE suppression_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS suppression_events_tenant_isolation ON suppression_events;
CREATE POLICY suppression_events_tenant_isolation ON suppression_events
  USING (tenant_id::text = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS suppression_events_append_only ON suppression_events;
CREATE POLICY suppression_events_append_only ON suppression_events
  FOR INSERT WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));

REVOKE UPDATE, DELETE ON suppression_events FROM PUBLIC;

-- A revocation must survive every other write path. Any process that flips
-- opted_out back to false is a defect; this view is the reconciliation source.
CREATE OR REPLACE VIEW suppressed_contacts AS
SELECT DISTINCT ON (tenant_id, contact_point)
  tenant_id,
  contact_point,
  contact_type,
  channel,
  action,
  occurred_at
FROM suppression_events
ORDER BY tenant_id, contact_point, occurred_at DESC;
