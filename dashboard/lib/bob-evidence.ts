export function bobEvidence(value: unknown, leadId: string, now = Date.now()) {
  if (!value || typeof value !== 'object') return null
  const b = value as { schema_version: string; lead_id: string; ready_for_call: boolean; created_at: string; expires_at: string; phase: string; missing_box: string; evidence?: { valuation?: { lead_id: string; status: string; method: string; purpose: string; quote_authorized: boolean; offer_authorized: boolean; as_of: string; supported_low_cents: number; point_cents: number; supported_high_cents: number; comparable_count: number } } }
  const created = Date.parse(b.created_at), expires = Date.parse(b.expires_at)
  if (b.schema_version !== '2.0' || b.lead_id !== leadId || b.ready_for_call !== false || !Number.isFinite(created) || !Number.isFinite(expires) || created > now || expires <= now || expires - created > 168 * 3600000) return null
  const v = b.evidence?.valuation
  const amounts = [v?.supported_low_cents ?? NaN, v?.point_cents ?? NaN, v?.supported_high_cents ?? NaN]
  const asOf = Date.parse(v?.as_of ?? ''), age = now - asOf
  const pricing = v?.lead_id === leadId && v?.status === 'ready_advisory' && v?.method === 'evidence_adjusted_sales_comparison' && ['as_is', 'after_repair'].includes(v?.purpose ?? '') && v?.quote_authorized === false && v?.offer_authorized === false && Number.isFinite(asOf) && age >= 0 && age <= 31 * 86400000 && amounts.every(a => Number.isSafeInteger(a) && a > 0 && a <= 1e14) && amounts[0] <= amounts[1] && amounts[1] <= amounts[2] && Number.isInteger(v.comparable_count) && v.comparable_count >= 3 && v.comparable_count <= 50
  return { phase: String(b.phase ?? '').slice(0, 40), missing: String(b.missing_box ?? '').slice(0, 40), expires: b.expires_at, pricing: pricing ? { low: amounts[0], point: amounts[1], high: amounts[2], count: v.comparable_count, purpose: v.purpose, asOf: v.as_of } : null }
}
