CREATE TABLE IF NOT EXISTS public.rentcast_calls (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES public.tenants(id),
  property_id uuid REFERENCES public.properties(id) ON DELETE SET NULL,
  reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  finished_at timestamptz,
  http_status integer,
  outcome text NOT NULL DEFAULT 'reserved' CHECK (outcome IN ('reserved', 'ok', 'no_data', 'error'))
);
CREATE INDEX IF NOT EXISTS rentcast_calls_reserved_at ON public.rentcast_calls (reserved_at DESC);
ALTER TABLE public.rentcast_calls ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.rentcast_calls FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.rentcast_calls TO service_role;

CREATE OR REPLACE FUNCTION public.rentcast_calls_hard_ceiling() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('rentcast_budget', 0));
  IF (SELECT count(*) FROM public.rentcast_calls WHERE reserved_at > clock_timestamp() - interval '31 days') >= 50 THEN
    RAISE EXCEPTION 'RentCast hard ceiling of 50 calls per 31 days reached';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS rentcast_calls_hard_ceiling ON public.rentcast_calls;
CREATE TRIGGER rentcast_calls_hard_ceiling BEFORE INSERT ON public.rentcast_calls
  FOR EACH ROW EXECUTE FUNCTION public.rentcast_calls_hard_ceiling();

CREATE OR REPLACE FUNCTION public.reserve_rentcast_call(p_tenant uuid, p_property uuid, p_cap integer)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE cap integer; used integer; reserved bigint;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('rentcast_budget', 0));
  cap := least(greatest(coalesce(p_cap, 0), 0), 50);
  SELECT count(*) INTO used FROM public.rentcast_calls WHERE reserved_at > clock_timestamp() - interval '31 days';
  IF used >= cap THEN RETURN NULL; END IF;
  INSERT INTO public.rentcast_calls (tenant_id, property_id) VALUES (p_tenant, p_property) RETURNING id INTO reserved;
  RETURN reserved;
END $$;

CREATE OR REPLACE FUNCTION public.finish_rentcast_call(p_id bigint, p_http_status integer, p_outcome text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE changed integer;
BEGIN
  IF p_outcome NOT IN ('ok', 'no_data', 'error') THEN RAISE EXCEPTION 'Invalid RentCast outcome'; END IF;
  UPDATE public.rentcast_calls SET finished_at = clock_timestamp(), http_status = p_http_status, outcome = p_outcome
  WHERE id = p_id AND outcome = 'reserved';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed = 1;
END $$;

CREATE OR REPLACE FUNCTION public.rentcast_usage()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT jsonb_build_object(
    'used', count(*),
    'hard_cap', 50,
    'window_days', 31,
    'oldest_in_window', min(reserved_at),
    'ok', count(*) FILTER (WHERE outcome = 'ok'),
    'no_data', count(*) FILTER (WHERE outcome = 'no_data'),
    'errors', count(*) FILTER (WHERE outcome = 'error'),
    'unfinished', count(*) FILTER (WHERE outcome = 'reserved'))
  FROM public.rentcast_calls WHERE reserved_at > clock_timestamp() - interval '31 days'
$$;

REVOKE ALL ON FUNCTION public.reserve_rentcast_call(uuid, uuid, integer), public.finish_rentcast_call(bigint, integer, text), public.rentcast_usage() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_rentcast_call(uuid, uuid, integer), public.finish_rentcast_call(bigint, integer, text), public.rentcast_usage() TO service_role;

ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS source_ref text;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS retrieved_at timestamptz;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS comp_kind text;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS list_price_cents bigint;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS listing_status text;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS listing_type text;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS listed_date date;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS removed_date date;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS correlation numeric;
ALTER TABLE public.comps ADD COLUMN IF NOT EXISTS year_built integer;
CREATE UNIQUE INDEX IF NOT EXISTS comps_source_identity ON public.comps (subject_property_id, source, source_ref);
