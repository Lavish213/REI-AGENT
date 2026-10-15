CREATE OR REPLACE FUNCTION public.resume_reviewed_email(p_id uuid,p_tenant uuid,p_lead uuid,p_actor uuid,p_reason text,p_email text,p_replies uuid[],p_fingerprint text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE l public.leads; r public.source_command_receipts; actual uuid[]; BEGIN
 IF p_id IS NULL OR p_actor IS NULL OR p_reason IS NULL OR length(trim(p_reason)) NOT BETWEEN 10 AND 1000 OR p_email IS NULL OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' OR coalesce(cardinality(p_replies),0) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'Explicit bounded reply review required'; END IF;
 SELECT * INTO l FROM public.leads WHERE id=p_lead AND tenant_id=p_tenant FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Canonical lead not found'; END IF;
 SELECT * INTO r FROM public.source_command_receipts WHERE id=p_id;
 IF FOUND THEN
  IF r.tenant_id=p_tenant AND r.lead_id=p_lead AND r.actor_id=p_actor AND r.action='resume_email_followups' AND r.fingerprint=p_fingerprint THEN RETURN p_id; END IF;
  RAISE EXCEPTION 'Conflicting resumption replay';
 END IF;
 IF l.opted_out IS DISTINCT FROM false OR coalesce(l.dnc_blocked,true) OR l.email_completed IS DISTINCT FROM false OR l.email_started_at IS NULL OR lower(trim(l.owner_email)) IS DISTINCT FROM p_email THEN RAISE EXCEPTION 'Existing campaign and eligible email identity required'; END IF;
 IF EXISTS(SELECT 1 FROM public.suppression_events WHERE tenant_id=p_tenant AND lead_id=p_lead AND action='suppressed' AND (channel='all' OR (channel='email' AND lower(trim(contact_point))=p_email))) THEN RAISE EXCEPTION 'Existing all-channel suppression remains blocked'; END IF;
 SELECT array_agg(id ORDER BY id) INTO actual FROM public.email_reply_events WHERE tenant_id=p_tenant AND lead_id=p_lead;
 IF actual IS DISTINCT FROM p_replies THEN RAISE EXCEPTION 'Reply evidence changed'; END IF;
 IF EXISTS(SELECT 1 FROM public.email_reply_events WHERE tenant_id=p_tenant AND lead_id=p_lead AND lower(btrim(body,chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||' ')) IN ('stop','unsubscribe','remove me','do not contact me')) THEN RAISE EXCEPTION 'STOP cannot be resumed'; END IF;
 UPDATE public.leads SET email_paused=false,updated_at=now() WHERE id=p_lead AND tenant_id=p_tenant;
 INSERT INTO public.source_command_receipts(id,tenant_id,lead_id,fingerprint,action,actor_id,reason,payload) VALUES(p_id,p_tenant,p_lead,p_fingerprint,'resume_email_followups',p_actor,trim(p_reason),jsonb_build_object('email',p_email,'reply_ids',p_replies));
 RETURN p_id;
END; $$;
REVOKE ALL ON FUNCTION public.resume_reviewed_email(uuid,uuid,uuid,uuid,text,text,uuid[],text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resume_reviewed_email(uuid,uuid,uuid,uuid,text,text,uuid[],text) TO service_role;
