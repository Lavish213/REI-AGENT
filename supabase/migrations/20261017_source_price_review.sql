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
