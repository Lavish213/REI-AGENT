CREATE TABLE IF NOT EXISTS public.email_reply_events (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(id), lead_id uuid NOT NULL REFERENCES public.leads(id),
 sender text NOT NULL, body text NOT NULL CHECK(length(body) BETWEEN 1 AND 10000), fingerprint text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.email_reply_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_reply_events FROM anon,authenticated;
GRANT SELECT ON public.email_reply_events TO service_role;
CREATE OR REPLACE FUNCTION public.apply_inbound_email(p_id uuid,p_tenant uuid,p_lead uuid,p_sender text,p_text text,p_fingerprint text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE existing public.email_reply_events; BEGIN
 PERFORM id FROM public.leads WHERE id=p_lead AND tenant_id=p_tenant AND lower(trim(owner_email))=p_sender FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Canonical email sender does not match'; END IF;
 SELECT * INTO existing FROM public.email_reply_events WHERE id=p_id;
 IF FOUND THEN
  IF existing.tenant_id<>p_tenant OR existing.lead_id<>p_lead OR existing.fingerprint<>p_fingerprint THEN RAISE EXCEPTION 'Conflicting reply replay'; END IF;
  RETURN p_id;
 END IF;
 INSERT INTO public.email_reply_events(id,tenant_id,lead_id,sender,body,fingerprint) VALUES(p_id,p_tenant,p_lead,p_sender,p_text,p_fingerprint);
 UPDATE public.leads SET email_paused=true,updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 IF lower(trim(p_text)) IN ('stop','unsubscribe','remove me','do not contact me') THEN
  UPDATE public.leads SET opted_out=true WHERE id=p_lead AND tenant_id=p_tenant;
 END IF;
 RETURN p_id;
END; $$;
REVOKE ALL ON FUNCTION public.apply_inbound_email(uuid,uuid,uuid,text,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_inbound_email(uuid,uuid,uuid,text,text,text) TO service_role;

CREATE TABLE IF NOT EXISTS public.source_command_receipts (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(id), lead_id uuid NOT NULL REFERENCES public.leads(id),
 fingerprint text NOT NULL, action text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.source_command_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.source_command_receipts FROM anon,authenticated;
GRANT SELECT ON public.source_command_receipts TO service_role;
CREATE OR REPLACE FUNCTION public.apply_source_callback(p_id uuid,p_tenant uuid,p_lead uuid,p_property uuid,p_expected timestamptz,p_at timestamptz,p_fingerprint text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE current_lead public.leads; receipt public.source_command_receipts; BEGIN
 SELECT * INTO current_lead FROM public.leads WHERE id=p_lead AND tenant_id=p_tenant FOR UPDATE;
 IF NOT FOUND OR current_lead.property_id IS DISTINCT FROM p_property THEN RAISE EXCEPTION 'Canonical source binding mismatch'; END IF;
 SELECT * INTO receipt FROM public.source_command_receipts WHERE id=p_id;
 IF FOUND THEN
  IF receipt.tenant_id<>p_tenant OR receipt.lead_id<>p_lead OR receipt.fingerprint<>p_fingerprint THEN RAISE EXCEPTION 'Conflicting command replay'; END IF;
  RETURN p_id;
 END IF;
 IF current_lead.updated_at IS DISTINCT FROM p_expected THEN RAISE EXCEPTION 'Source version changed; refresh required'; END IF;
 IF current_lead.opted_out THEN RAISE EXCEPTION 'Contact suppression active'; END IF;
 IF p_at<=now() OR p_at>now()+interval '90 days' THEN RAISE EXCEPTION 'Future bounded callback required'; END IF;
 INSERT INTO public.source_command_receipts(id,tenant_id,lead_id,fingerprint,action) VALUES(p_id,p_tenant,p_lead,p_fingerprint,'schedule_callback');
 UPDATE public.leads SET callback_scheduled_at=p_at,callback_claimed_until=NULL,callback_claim_token=NULL,updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 RETURN p_id;
END; $$;
REVOKE ALL ON FUNCTION public.apply_source_callback(uuid,uuid,uuid,uuid,timestamptz,timestamptz,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_source_callback(uuid,uuid,uuid,uuid,timestamptz,timestamptz,text) TO service_role;
