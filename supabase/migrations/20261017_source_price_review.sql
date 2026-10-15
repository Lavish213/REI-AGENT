CREATE OR REPLACE FUNCTION public.resolve_source_price_review(p_id text,p_tenant uuid,p_actor uuid,p_status text,p_reason text,p_low bigint,p_high bigint,p_expected jsonb,p_decision text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE a public.approval_requests; l public.leads; ctx jsonb; BEGIN
 IF p_actor IS NULL OR p_status IS NULL OR p_reason IS NULL OR p_decision IS NULL OR p_status NOT IN ('approved','rejected') OR length(trim(p_reason)) NOT BETWEEN 10 AND 1000 OR p_decision !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Explicit actor and bounded decision required'; END IF;
 SELECT * INTO a FROM public.approval_requests WHERE id::text=p_id AND tenant_id=p_tenant FOR UPDATE;
 IF NOT FOUND OR a.approval_type<>'price_review' THEN RAISE EXCEPTION 'Price review not found'; END IF;
 IF a.status IS DISTINCT FROM 'pending' THEN
  IF a.status=p_status AND a.approved_by::text=p_actor::text AND a.context_snapshot->>'source_decision_fingerprint'=p_decision THEN RETURN p_id; END IF;
  RAISE EXCEPTION 'Conflicting resolved decision';
 END IF;
 IF a.expires_at IS NULL OR a.expires_at<=now() OR a.lead_id::text IS DISTINCT FROM p_expected->>'lead_id' OR a.call_sid IS DISTINCT FROM p_expected->>'call_sid' OR a.requested_action IS DISTINCT FROM p_expected->>'requested_action' OR a.expires_at IS DISTINCT FROM (p_expected->>'expires_at')::timestamptz OR coalesce(a.context_snapshot,'{}'::jsonb) IS DISTINCT FROM p_expected->'context_snapshot' THEN RAISE EXCEPTION 'Review expired or changed'; END IF;
 SELECT * INTO l FROM public.leads WHERE id=a.lead_id AND tenant_id=p_tenant FOR UPDATE;
 IF NOT FOUND OR l.property_id IS NULL OR l.property_id::text IS DISTINCT FROM p_expected->>'property_id' THEN RAISE EXCEPTION 'Canonical property changed'; END IF;
 PERFORM id FROM public.properties WHERE id=l.property_id AND tenant_id=p_tenant;
 IF NOT FOUND THEN RAISE EXCEPTION 'Canonical property tenant mismatch'; END IF;
 IF p_status='approved' AND (a.call_sid IS NULL OR length(a.call_sid)=0 OR a.requested_action NOT IN ('get_offer_range','send_offer_summary','collect_and_send_email','send_followup_email') OR p_low IS NULL OR p_high IS NULL OR p_low<=0 OR p_high<p_low OR p_high>100000000000000 OR p_low%100<>0 OR p_high%100<>0 OR coalesce(l.opted_out,false)) THEN RAISE EXCEPTION 'Valid whole-dollar cents and callable subject required'; END IF;
 ctx=coalesce(a.context_snapshot,'{}'::jsonb)||jsonb_build_object('answer',trim(p_reason),'source_decision_fingerprint',p_decision);
 IF p_status='approved' THEN ctx=ctx||jsonb_build_object('property_id',l.property_id,'offer_low_cents',p_low,'offer_high_cents',p_high); END IF;
 UPDATE public.approval_requests SET status=p_status,approved_by=p_actor::text,resolved_at=now(),context_snapshot=ctx WHERE id=a.id AND tenant_id=p_tenant;
 RETURN p_id;
END; $$;
REVOKE ALL ON FUNCTION public.resolve_source_price_review(text,uuid,uuid,text,text,bigint,bigint,jsonb,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_source_price_review(text,uuid,uuid,text,text,bigint,bigint,jsonb,text) TO service_role;
CREATE OR REPLACE FUNCTION public.request_source_price_review(p_tenant uuid,p_lead uuid,p_call text,p_action text,p_reason text,p_context jsonb,p_minutes integer)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE existing public.approval_requests; fresh public.approval_requests.id%TYPE; BEGIN
 IF p_call IS NULL OR length(trim(p_call)) NOT BETWEEN 1 AND 255 OR p_action IS NULL OR p_action NOT IN ('get_offer_range','send_offer_summary','collect_and_send_email','send_followup_email') OR p_reason IS NULL OR length(p_reason)>1000 OR p_minutes IS NULL OR p_minutes NOT BETWEEN 1 AND 30 OR jsonb_typeof(p_context) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Bounded price request required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_tenant::text||':'||p_lead::text||':'||p_call||':'||p_action,0));
 PERFORM l.id FROM public.leads l JOIN public.properties p ON p.id=l.property_id AND p.tenant_id=l.tenant_id WHERE l.id=p_lead AND l.tenant_id=p_tenant AND NOT coalesce(l.opted_out,false) FOR UPDATE OF l;
 IF NOT FOUND THEN RAISE EXCEPTION 'Canonical price subject unavailable'; END IF;
 SELECT * INTO existing FROM public.approval_requests WHERE tenant_id=p_tenant AND lead_id=p_lead AND call_sid=p_call AND requested_action=p_action AND approval_type='price_review' AND status='pending' AND expires_at>now() ORDER BY expires_at LIMIT 1;
 IF FOUND THEN RETURN existing.id::text; END IF;
 fresh=replace(gen_random_uuid()::text,'-','');
 INSERT INTO public.approval_requests(id,tenant_id,lead_id,call_sid,idempotency_key,approval_type,requested_action,risk_reason,context_snapshot,expires_at,priority,expires_reason,status) VALUES(fresh,p_tenant,p_lead,p_call,fresh::text,'price_review',p_action,p_reason,p_context,now()+make_interval(mins=>p_minutes),'high','call_timeout','pending');
 RETURN fresh::text;
END; $$;
REVOKE ALL ON FUNCTION public.request_source_price_review(uuid,uuid,text,text,text,jsonb,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.request_source_price_review(uuid,uuid,text,text,text,jsonb,integer) TO service_role;
