CREATE TABLE IF NOT EXISTS public.provider_delivery_events (
  tenant_id uuid NOT NULL,
  id text NOT NULL,
  intent_id text NOT NULL,
  lead_id uuid,
  payload jsonb NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS public.provider_delivery_messages (
  tenant_id uuid NOT NULL,
  intent_id text NOT NULL,
  lead_id uuid,
  channel text NOT NULL,
  recipient text NOT NULL,
  delivery_status text NOT NULL DEFAULT 'unknown',
  opened boolean NOT NULL DEFAULT false,
  clicked boolean NOT NULL DEFAULT false,
  suppressed boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,intent_id)
);
ALTER TABLE public.provider_delivery_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_delivery_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.provider_delivery_events,public.provider_delivery_messages FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.provider_delivery_events,public.provider_delivery_messages TO service_role;

CREATE OR REPLACE FUNCTION public.apply_delivery_event(p_tenant uuid,p_id text,p_intent text,p_lead uuid,p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  existing public.provider_delivery_events%ROWTYPE;
  current_message public.provider_delivery_messages%ROWTYPE;
  status text;
  success boolean;
  failure boolean;
  seen_open boolean;
  seen_click boolean;
  seen_suppression boolean;
BEGIN
  IF p_tenant IS NULL OR p_id IS NULL OR p_intent IS NULL OR p_payload IS NULL
    OR p_id !~ '^[a-f0-9]{64}$' OR p_intent !~ '^[a-f0-9]{64}$'
    OR p_payload->>'channel' NOT IN ('sms','email')
    OR coalesce(length(p_payload->>'recipient'),0) NOT BETWEEN 3 AND 320
    OR coalesce(length(p_payload->>'message_id'),0) NOT BETWEEN 1 AND 512
    OR coalesce(p_payload->>'status','') NOT IN ('accepted','queued','sending','sent','delivered','undelivered','failed','read','canceled','processed','deferred','dropped','bounce','open','click','spamreport','unsubscribe','group_unsubscribe','group_resubscribe')
  THEN RAISE EXCEPTION 'Invalid delivery evidence'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_tenant::text || p_intent,0));
  SELECT * INTO existing FROM public.provider_delivery_events WHERE tenant_id=p_tenant AND id=p_id;
  IF FOUND THEN
    IF existing.intent_id <> p_intent OR existing.lead_id IS DISTINCT FROM p_lead OR existing.payload <> p_payload THEN
      RAISE EXCEPTION 'Delivery replay conflict';
    END IF;
    RETURN p_id;
  END IF;
  SELECT * INTO current_message FROM public.provider_delivery_messages WHERE tenant_id=p_tenant AND intent_id=p_intent FOR UPDATE;
  IF FOUND AND (current_message.lead_id IS DISTINCT FROM p_lead OR current_message.channel <> p_payload->>'channel' OR current_message.recipient <> p_payload->>'recipient') THEN
    RAISE EXCEPTION 'Message binding conflict';
  END IF;
  INSERT INTO public.provider_delivery_events(tenant_id,id,intent_id,lead_id,payload) VALUES(p_tenant,p_id,p_intent,p_lead,p_payload);
  SELECT bool_or(payload->>'status' IN ('delivered','read')),
    bool_or(payload->>'status' IN ('failed','undelivered','canceled','bounce','dropped')),
    bool_or(payload->>'status'='open'),bool_or(payload->>'status'='click'),
    bool_or(payload->>'status' IN ('spamreport','unsubscribe','group_unsubscribe','bounce','dropped'))
    INTO success,failure,seen_open,seen_click,seen_suppression
    FROM public.provider_delivery_events WHERE tenant_id=p_tenant AND intent_id=p_intent;
  status := CASE WHEN success AND failure THEN 'conflicting_receipts' WHEN success THEN 'delivered' WHEN failure THEN 'failed' ELSE 'pending' END;
  INSERT INTO public.provider_delivery_messages(tenant_id,intent_id,lead_id,channel,recipient,delivery_status,opened,clicked,suppressed)
    VALUES(p_tenant,p_intent,p_lead,p_payload->>'channel',p_payload->>'recipient',status,seen_open,seen_click,seen_suppression)
    ON CONFLICT(tenant_id,intent_id) DO UPDATE SET delivery_status=excluded.delivery_status,opened=excluded.opened,clicked=excluded.clicked,suppressed=excluded.suppressed,updated_at=now();
  IF p_payload->>'channel'='email' AND seen_suppression AND p_lead IS NOT NULL THEN
    UPDATE public.leads SET email_paused=true,updated_at=now()
      WHERE tenant_id=p_tenant AND id=p_lead AND lower(btrim(owner_email))=p_payload->>'recipient';
  END IF;
  IF p_payload->>'channel'='email' AND p_payload->>'status' IN ('unsubscribe','group_unsubscribe','spamreport') AND p_lead IS NOT NULL THEN
    UPDATE public.leads SET opted_out=true,email_paused=true,updated_at=now()
      WHERE tenant_id=p_tenant AND id=p_lead AND lower(btrim(owner_email))=p_payload->>'recipient';
  END IF;
  IF p_payload->>'channel'='sms' AND to_regclass('public.sms_messages') IS NOT NULL THEN
    UPDATE public.sms_messages SET delivery_status=status,updated_at=now()
      WHERE tenant_id=p_tenant AND signalwire_message_id=p_payload->>'message_id' AND direction='outbound' AND lead_id IS NOT DISTINCT FROM p_lead;
  END IF;
  RETURN p_id;
END $$;
REVOKE ALL ON FUNCTION public.apply_delivery_event(uuid,text,text,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_delivery_event(uuid,text,text,uuid,jsonb) TO service_role;
