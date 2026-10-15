ALTER TABLE public.source_command_receipts ADD COLUMN IF NOT EXISTS actor_id uuid;
ALTER TABLE public.source_command_receipts ADD COLUMN IF NOT EXISTS reason text;
ALTER TABLE public.source_command_receipts ADD COLUMN IF NOT EXISTS payload jsonb;
CREATE OR REPLACE FUNCTION public.apply_source_operation(p_id uuid,p_tenant uuid,p_lead uuid,p_property uuid,p_expected timestamptz,p_action text,p_payload jsonb,p_actor uuid,p_reason text,p_fingerprint text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE l public.leads; r public.source_command_receipts; appointment uuid; amount bigint; repairs bigint; arv bigint; value numeric; k text; BEGIN
 IF p_actor IS NULL OR p_id IS NULL OR p_reason IS NULL OR length(trim(p_reason)) NOT BETWEEN 10 AND 1000 OR p_action IS NULL OR p_action NOT IN ('set_disposition','cancel_walkthrough','draft_offer') OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Bounded explicit operation required'; END IF;
 SELECT * INTO l FROM public.leads WHERE id=p_lead AND tenant_id=p_tenant AND property_id=p_property FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Canonical subject mismatch'; END IF;
 SELECT * INTO r FROM public.source_command_receipts WHERE id=p_id;
 IF FOUND THEN
  IF r.tenant_id=p_tenant AND r.lead_id=p_lead AND r.action=p_action AND r.fingerprint=p_fingerprint AND r.actor_id=p_actor THEN RETURN p_id; END IF;
  RAISE EXCEPTION 'Conflicting operation replay';
 END IF;
 IF l.updated_at IS DISTINCT FROM p_expected THEN RAISE EXCEPTION 'Source version changed'; END IF;
 PERFORM id FROM public.properties WHERE id=p_property AND tenant_id=p_tenant;
 IF NOT FOUND THEN RAISE EXCEPTION 'Property tenant mismatch'; END IF;
 IF p_action='set_disposition' THEN
  IF p_payload->>'disposition' IS NULL OR p_payload->>'disposition' NOT IN ('HOT','WARM','COLD','DEAD') THEN RAISE EXCEPTION 'Invalid disposition'; END IF;
  UPDATE public.leads SET disposition=p_payload->>'disposition',callable=CASE WHEN p_payload->>'disposition'='DEAD' THEN false ELSE callable END,updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 ELSIF p_action='cancel_walkthrough' THEN
  SELECT id INTO appointment FROM public.voice_appointments WHERE lead_id=p_lead AND starts_at=(p_payload->>'starts_at')::timestamptz AND status='confirmed' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Confirmed reservation changed'; END IF;
  UPDATE public.voice_appointments SET status='cancelled' WHERE id=appointment;
  UPDATE public.leads SET appointment_at=CASE WHEN appointment_at=(p_payload->>'starts_at')::timestamptz THEN NULL ELSE appointment_at END,updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 ELSE
  FOREACH k IN ARRAY ARRAY['amount_cents','repair_cents','arv_cents'] LOOP
   IF k='arv_cents' AND p_payload->k='null'::jsonb THEN CONTINUE; END IF;
   IF jsonb_typeof(p_payload->k) IS DISTINCT FROM 'number' THEN RAISE EXCEPTION 'Integer cents required'; END IF;
   value=(p_payload->>k)::numeric;
   IF value<>trunc(value) OR value<0 OR value>100000000000000 OR (k<>'repair_cents' AND value=0) THEN RAISE EXCEPTION 'Bounded positive money required'; END IF;
  END LOOP;
  IF coalesce(l.opted_out,false) THEN RAISE EXCEPTION 'Subject opted out'; END IF;
  amount=(p_payload->>'amount_cents')::bigint; repairs=(p_payload->>'repair_cents')::bigint; arv=(p_payload->>'arv_cents')::bigint;
  INSERT INTO public.offers(id,tenant_id,lead_id,property_id,arv_used,repair_estimate,mao_calculated,offer_amount,offer_status,notes,created_by) VALUES(p_id,p_tenant,p_lead,p_property,arv,repairs,CASE WHEN arv IS NULL THEN NULL ELSE greatest(0,floor(arv::numeric*70/100)::bigint-repairs) END,amount,'draft',trim(p_reason),p_actor::text);
  UPDATE public.leads SET updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 END IF;
 INSERT INTO public.source_command_receipts(id,tenant_id,lead_id,fingerprint,action,actor_id,reason,payload) VALUES(p_id,p_tenant,p_lead,p_fingerprint,p_action,p_actor,trim(p_reason),p_payload);
 RETURN p_id;
END; $$;
REVOKE ALL ON FUNCTION public.apply_source_operation(uuid,uuid,uuid,uuid,timestamptz,text,jsonb,uuid,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_source_operation(uuid,uuid,uuid,uuid,timestamptz,text,jsonb,uuid,text,text) TO service_role;
