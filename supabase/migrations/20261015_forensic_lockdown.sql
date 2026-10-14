CREATE OR REPLACE FUNCTION public.create_canonical_lead(p_tenant_id uuid, p_property_id uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE result uuid; n integer;
BEGIN
  PERFORM id FROM public.properties WHERE id=p_property_id AND tenant_id=p_tenant_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Canonical property missing'; END IF;
  SELECT count(*), min(id::text)::uuid INTO n, result FROM public.leads WHERE property_id=p_property_id AND tenant_id=p_tenant_id;
  IF n>1 THEN RAISE EXCEPTION 'Ambiguous lead binding'; END IF;
  IF n=0 THEN
    INSERT INTO public.leads(property_id,tenant_id,stage,callable) VALUES(p_property_id,p_tenant_id,'new',false) RETURNING id INTO result;
  END IF;
  UPDATE public.properties SET lead_id=result WHERE id=p_property_id AND tenant_id=p_tenant_id;
  RETURN result;
END;
$$;
REVOKE ALL ON FUNCTION public.create_canonical_lead(uuid,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_canonical_lead(uuid,uuid) TO service_role;
CREATE TABLE IF NOT EXISTS public.source_candidates (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(id), source text NOT NULL, source_ref text NOT NULL,
 payload jsonb NOT NULL, fingerprint text NOT NULL, observed_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'needs_property_review', contact_authorized boolean NOT NULL DEFAULT false CHECK (NOT contact_authorized), offer_authorized boolean NOT NULL DEFAULT false CHECK (NOT offer_authorized)
);
CREATE UNIQUE INDEX IF NOT EXISTS source_candidates_identity ON public.source_candidates(tenant_id,source,source_ref);
ALTER TABLE public.source_candidates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.source_candidates FROM anon, authenticated;
GRANT ALL ON public.source_candidates TO service_role;
CREATE TABLE IF NOT EXISTS public.email_suppressions (
 tenant_id uuid NOT NULL REFERENCES public.tenants(id), email text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,email)
);
ALTER TABLE public.email_suppressions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_suppressions FROM anon, authenticated;
GRANT SELECT,INSERT ON public.email_suppressions TO service_role;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS email_started_at timestamptz;
ALTER TABLE public.properties ADD COLUMN IF NOT EXISTS valuation_diagnostic jsonb;

CREATE OR REPLACE FUNCTION public.reject_tenant_reassignment() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN RAISE EXCEPTION 'Tenant identity is immutable'; END IF;
 RETURN NEW;
END; $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['leads','properties','contacts','calls','dnc_list','cash_buyers','approval_requests','source_candidates'] LOOP
  IF to_regclass('public.'||t) IS NOT NULL THEN
   EXECUTE format('DROP TRIGGER IF EXISTS immutable_tenant ON public.%I',t);
   EXECUTE format('CREATE TRIGGER immutable_tenant BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_tenant_reassignment()',t);
  END IF;
 END LOOP;
END; $$;
