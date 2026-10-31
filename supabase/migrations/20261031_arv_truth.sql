UPDATE public.properties
SET estimated_arv = NULL, mao = NULL, arv_confidence = 'needs_comps', updated_at = now()
WHERE estimated_arv IS NOT NULL
  AND (
    (assessed_total_value > 0 AND abs(estimated_arv - round(assessed_total_value / 0.80)) <= 1)
    OR (estimated_arv > 0 AND estimated_arv < 1000000)
  );

UPDATE public.properties
SET mao = NULL, updated_at = now()
WHERE mao IS NOT NULL AND mao > 0 AND mao < 1000000;

ALTER TABLE public.properties DROP CONSTRAINT IF EXISTS properties_arv_cents_check;
ALTER TABLE public.properties ADD CONSTRAINT properties_arv_cents_check
  CHECK (estimated_arv IS NULL OR estimated_arv = 0 OR estimated_arv >= 1000000);

ALTER TABLE public.properties DROP CONSTRAINT IF EXISTS properties_mao_cents_check;
ALTER TABLE public.properties ADD CONSTRAINT properties_mao_cents_check
  CHECK (mao IS NULL OR mao = 0 OR mao >= 1000000);
