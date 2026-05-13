import { supabase } from '@/lib/supabase'
import { notFound } from 'next/navigation'

const API = process.env.NEXT_PUBLIC_API_URL || ''

function formatCurrency(cents: number | null | undefined) {
  if (cents == null) return '—'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function formatDateShort(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return '—'
  const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

function StageBadge({ stage }: { stage: string | null }) {
  if (!stage) return <span className="text-gray-500 text-xs">—</span>
  const cls: Record<string, string> = {
    new: 'bg-blue-900/50 text-blue-300',
    contacted: 'bg-yellow-900/50 text-yellow-300',
    offer_made: 'bg-orange-900/50 text-orange-300',
    walkthrough_booked: 'bg-green-900/50 text-green-300',
    under_contract: 'bg-purple-900/50 text-purple-300',
    closed: 'bg-green-800 text-green-200',
    dead: 'bg-gray-700 text-gray-500',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls[stage] ?? 'bg-gray-700 text-gray-300'}`}>
      {stage.replace(/_/g, ' ')}
    </span>
  )
}

function WorkflowBadge({ state }: { state: string | null }) {
  if (!state) return null
  const cls: Record<string, string> = {
    new_lead: 'bg-gray-700 text-gray-300',
    active_contact: 'bg-blue-900/50 text-blue-200',
    followup_required: 'bg-yellow-900/50 text-yellow-200',
    appointment_pending: 'bg-orange-900/50 text-orange-200',
    appointment_confirmed: 'bg-green-800 text-green-200',
    negotiation: 'bg-purple-900/50 text-purple-200',
    under_review: 'bg-indigo-900/50 text-indigo-200',
    dead_lead: 'bg-gray-700 text-gray-500',
    closed: 'bg-green-900 text-green-300',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${cls[state] ?? 'bg-gray-700 text-gray-300'}`}>
      {state.replace(/_/g, ' ')}
    </span>
  )
}

function PriorityBadge({ priority }: { priority: string | null }) {
  if (!priority) return null
  const cls: Record<string, string> = {
    high: 'bg-red-900/50 text-red-300',
    medium: 'bg-yellow-900/50 text-yellow-300',
    low: 'bg-gray-700 text-gray-400',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${cls[priority] ?? cls.low}`}>
      {priority}
    </span>
  )
}

function OfferStatusBadge({ status }: { status: string | null }) {
  if (!status) return null
  const cls: Record<string, string> = {
    draft: 'bg-gray-700 text-gray-400',
    sent: 'bg-blue-900/50 text-blue-300',
    countered: 'bg-yellow-900/50 text-yellow-300',
    accepted: 'bg-green-800 text-green-200',
    rejected: 'bg-red-900/50 text-red-400',
    expired: 'bg-gray-700 text-gray-500',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls[status] ?? 'bg-gray-700 text-gray-300'}`}>
      {status}
    </span>
  )
}

function WalkthroughBadge({ state }: { state: string | null }) {
  if (!state || state === 'none') return <span className="text-gray-600 text-xs">none</span>
  const cls: Record<string, string> = {
    scheduled: 'text-blue-400',
    completed: 'text-green-400',
    missed: 'text-yellow-400',
    cancelled: 'text-gray-500',
  }
  return <span className={`text-xs font-medium ${cls[state] ?? 'text-gray-400'}`}>{state}</span>
}

function DispositionBadge({ disposition }: { disposition: string | null }) {
  if (!disposition) return <span className="text-gray-500 text-xs">—</span>
  const colors: Record<string, string> = {
    HOT: 'bg-red-700 text-red-100',
    WARM: 'bg-yellow-700 text-yellow-100',
    COLD: 'bg-blue-800 text-blue-200',
    DEAD: 'bg-gray-700 text-gray-400',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${colors[disposition] ?? 'bg-gray-700 text-gray-400'}`}>
      {disposition}
    </span>
  )
}

function MotivBar({ level }: { level: number | null }) {
  if (level == null) return <span className="text-gray-600 text-xs">unknown</span>
  const color = level >= 8 ? 'bg-red-500' : level >= 6 ? 'bg-yellow-500' : 'bg-gray-500'
  const textColor = level >= 8 ? 'text-red-400' : level >= 6 ? 'text-yellow-400' : 'text-gray-400'
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-0.5">
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className={`h-2.5 w-1.5 rounded-sm ${i < level ? color : 'bg-gray-700'}`} />
        ))}
      </div>
      <span className={`text-xs font-semibold ${textColor}`}>{level}/10</span>
    </div>
  )
}

export default async function LeadDetailPage({ params }: { params: { id: string } }) {
  const { id } = params

  const [
    leadRes,
    callsRes,
    workflowRes,
    followupsRes,
    eventsRes,
    offersRes,
  ] = await Promise.all([
    supabase
      .from('leads')
      .select('*, properties(*)')
      .eq('id', id)
      .single(),

    supabase
      .from('calls')
      .select('id, created_at, call_disposition, call_summary, score_overall, seller_name, seller_motivation, asking_price, appointment_interest, next_step, followup_priority, lead_score, distress_indicators, objections, property_condition, occupancy, timeline, extraction_confidence')
      .eq('lead_id', id)
      .order('created_at', { ascending: false })
      .limit(10),

    supabase
      .from('workflows')
      .select('id, state, previous_state, trigger_source, triggered_by, created_at')
      .eq('lead_id', id)
      .order('created_at', { ascending: false })
      .limit(20),

    supabase
      .from('followups')
      .select('*')
      .eq('lead_id', id)
      .eq('state', 'pending')
      .order('priority')
      .order('created_at')
      .limit(15),

    supabase
      .from('call_events')
      .select('event_type, payload, created_at')
      .eq('lead_id', id)
      .order('created_at', { ascending: false })
      .limit(25),

    supabase
      .from('offers')
      .select('*')
      .eq('lead_id', id)
      .order('created_at', { ascending: false }),
  ])

  if (!leadRes.data) notFound()

  const lead = leadRes.data as any
  const prop = (lead.properties as any) ?? {}
  const calls = callsRes.data ?? []
  const workflowHistory = workflowRes.data ?? []
  const followups = followupsRes.data ?? []
  const events = eventsRes.data ?? []
  const offers = offersRes.data ?? []
  const latestCall = calls[0] ?? null

  const address = prop.address ?? lead.address ?? '—'
  const hasHotIndicator = lead.is_hot_lead || lead.escalated

  // Compute MAO display from property
  const arvCents = prop.estimated_arv ?? null
  const maoCents = prop.mao ?? null

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6 max-w-7xl mx-auto">

      {/* Header */}
      <div className="mb-6">
        <a href="/leads" className="text-blue-400 text-sm hover:underline mb-2 inline-block">← Back to leads</a>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              {hasHotIndicator && (
                <span className="bg-red-900/60 text-red-300 text-xs px-2 py-0.5 rounded font-semibold">
                  {lead.escalated ? 'ESCALATED' : 'HOT LEAD'}
                </span>
              )}
              <h1 className="text-2xl font-bold">{address}</h1>
            </div>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <StageBadge stage={lead.stage} />
              <WorkflowBadge state={lead.workflow_state} />
              {lead.followup_urgency != null && lead.followup_urgency >= 7 && (
                <span className="text-xs text-red-400 font-semibold">Urgency {lead.followup_urgency}/10</span>
              )}
            </div>
          </div>

          {/* Quick actions */}
          <div className="flex flex-wrap gap-2">
            <form action={`${API}/api/workflow/leads/${id}/escalate`} method="POST">
              <button type="submit" className="text-xs px-3 py-1.5 bg-red-900/40 text-red-300 rounded hover:bg-red-900/60">
                Escalate
              </button>
            </form>
            <a
              href={`/leads/${id}/offer`}
              className="text-xs px-3 py-1.5 bg-green-900/40 text-green-300 rounded hover:bg-green-900/60"
            >
              + Offer
            </a>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* ─── Left: 2/3 wide ─── */}
        <div className="lg:col-span-2 space-y-5">

          {/* Seller Intelligence */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Seller Intelligence</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-500 mb-1">Motivation Level</p>
                <MotivBar level={lead.motivation_level} />
                {lead.seller_motivation && (
                  <p className="text-xs text-gray-400 mt-1.5 italic leading-snug">{lead.seller_motivation}</p>
                )}
              </div>
              <div className="space-y-2">
                {lead.timeline_urgency && (
                  <div>
                    <p className="text-xs text-gray-500">Timeline</p>
                    <p className={`text-sm capitalize font-medium ${
                      lead.timeline_urgency === 'immediate' ? 'text-red-400' :
                      lead.timeline_urgency === 'weeks' ? 'text-yellow-400' : 'text-gray-300'
                    }`}>{lead.timeline_urgency}</p>
                  </div>
                )}
                {lead.followup_urgency != null && (
                  <div>
                    <p className="text-xs text-gray-500">Followup Urgency</p>
                    <p className={`text-sm font-mono font-semibold ${
                      lead.followup_urgency >= 8 ? 'text-red-400' :
                      lead.followup_urgency >= 5 ? 'text-yellow-400' : 'text-gray-400'
                    }`}>{lead.followup_urgency}/10</p>
                  </div>
                )}
              </div>
            </div>
            {lead.call_summary && (
              <div className="mt-4 pt-4 border-t border-gray-700">
                <p className="text-xs text-gray-500 mb-1">Latest Summary</p>
                <p className="text-sm text-gray-200 leading-relaxed italic">{lead.call_summary}</p>
              </div>
            )}
            {lead.next_best_action && (
              <div className="mt-3">
                <p className="text-xs text-gray-500 mb-1">Next Best Action</p>
                <p className="text-sm text-blue-300">{lead.next_best_action}</p>
              </div>
            )}
          </section>

          {/* Property Intel */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Property Intelligence</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
              <div>
                <p className="text-xs text-gray-500">Distress Score</p>
                <p className={`text-2xl font-bold font-mono ${
                  (prop.distress_score ?? 0) >= 80 ? 'text-red-400' :
                  (prop.distress_score ?? 0) >= 60 ? 'text-yellow-400' : 'text-gray-300'
                }`}>{prop.distress_score ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Est. ARV</p>
                <p className="text-lg font-semibold text-gray-200">{formatCurrency(arvCents)}</p>
                {prop.arv_confidence && (
                  <p className="text-xs text-gray-600 capitalize">{prop.arv_confidence} confidence</p>
                )}
              </div>
              <div>
                <p className="text-xs text-gray-500">MAO</p>
                <p className="text-lg font-semibold text-green-400">{formatCurrency(maoCents)}</p>
                <p className="text-xs text-gray-600">70% ARV − $25k</p>
              </div>
              {latestCall?.asking_price != null && (
                <div>
                  <p className="text-xs text-gray-500">Asking Price</p>
                  <p className="text-lg font-semibold text-yellow-300">{formatCurrency(latestCall.asking_price)}</p>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              {prop.beds && <div><span className="text-gray-500 text-xs">Beds </span><span className="text-gray-200">{prop.beds}</span></div>}
              {prop.baths && <div><span className="text-gray-500 text-xs">Baths </span><span className="text-gray-200">{prop.baths}</span></div>}
              {prop.sqft && <div><span className="text-gray-500 text-xs">Sqft </span><span className="text-gray-200">{prop.sqft?.toLocaleString()}</span></div>}
              {prop.year_built && <div><span className="text-gray-500 text-xs">Built </span><span className="text-gray-200">{prop.year_built}</span></div>}
              {prop.property_type && <div><span className="text-gray-500 text-xs">Type </span><span className="text-gray-200 capitalize">{prop.property_type}</span></div>}
              {prop.county && <div><span className="text-gray-500 text-xs">County </span><span className="text-gray-200">{prop.county}</span></div>}
            </div>
            {latestCall?.property_condition && latestCall.property_condition !== 'unknown' && (
              <div className="mt-3 pt-3 border-t border-gray-700">
                <span className="text-xs text-gray-500">Condition (from call): </span>
                <span className="text-xs text-gray-300 capitalize">{latestCall.property_condition}</span>
                {latestCall.occupancy && latestCall.occupancy !== 'unknown' && (
                  <span className="text-xs text-gray-400 ml-3 capitalize"> · {latestCall.occupancy.replace(/_/g, ' ')}</span>
                )}
              </div>
            )}
          </section>

          {/* Call History */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Call History
              <span className="text-gray-600 ml-2 font-normal normal-case">({calls.length})</span>
            </h2>
            {calls.length === 0 ? (
              <p className="text-gray-600 text-sm">No calls yet</p>
            ) : (
              <div className="space-y-2">
                {calls.map((call: any) => (
                  <div key={call.id} className="border border-gray-700 rounded-lg p-3">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-xs text-gray-500 shrink-0">{formatDateShort(call.created_at)}</span>
                      <DispositionBadge disposition={call.call_disposition} />
                      {call.score_overall != null && (
                        <span className={`text-xs font-mono font-semibold ${
                          call.score_overall >= 8 ? 'text-green-400' :
                          call.score_overall >= 6 ? 'text-yellow-400' : 'text-red-400'
                        }`}>QA {call.score_overall.toFixed(1)}</span>
                      )}
                      {call.lead_score != null && (
                        <span className="text-xs text-gray-500 font-mono">Lead {call.lead_score.toFixed(1)}</span>
                      )}
                      <a href={`/calls/${call.id}`} className="text-xs text-blue-400 hover:underline ml-auto shrink-0">View →</a>
                    </div>
                    {call.call_summary && (
                      <p className="text-xs text-gray-400 mt-1.5 italic leading-tight line-clamp-2">{call.call_summary}</p>
                    )}
                    {call.next_step && (
                      <p className="text-xs text-blue-300 mt-1">→ {call.next_step}</p>
                    )}
                    {Array.isArray(call.distress_indicators) && call.distress_indicators.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {call.distress_indicators.map((d: string, i: number) => (
                          <span key={i} className="text-xs bg-red-900/30 text-red-400 px-1.5 py-0.5 rounded">{d}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Workflow Timeline */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Workflow Timeline</h2>
            {workflowHistory.length === 0 ? (
              <p className="text-gray-600 text-sm">No workflow transitions yet</p>
            ) : (
              <div className="space-y-2">
                {workflowHistory.map((wf: any) => (
                  <div key={wf.id} className="flex items-center gap-3 text-xs">
                    <span className="text-gray-600 w-20 shrink-0">{timeAgo(wf.created_at)}</span>
                    <WorkflowBadge state={wf.state} />
                    {wf.previous_state && (
                      <span className="text-gray-600">from {wf.previous_state.replace(/_/g, ' ')}</span>
                    )}
                    <span className="text-gray-600 ml-auto capitalize">{wf.trigger_source?.replace(/_/g, ' ')}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Operator Notes */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Operator Notes</h2>
            {lead.operator_notes ? (
              <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">{lead.operator_notes}</p>
            ) : (
              <p className="text-gray-600 text-sm italic">No notes yet</p>
            )}
            <form
              action={`${API}/api/workflow/leads/${id}/notes`}
              method="POST"
              className="mt-3"
            >
              <textarea
                name="notes"
                defaultValue={lead.operator_notes ?? ''}
                rows={3}
                className="w-full bg-gray-700 rounded text-sm text-gray-200 px-3 py-2 border border-gray-600 focus:border-blue-500 focus:outline-none resize-none"
                placeholder="Add operator notes..."
              />
              <button type="submit" className="mt-2 text-xs px-3 py-1.5 bg-blue-800 text-blue-200 rounded hover:bg-blue-700">
                Save Notes
              </button>
            </form>
          </section>
        </div>

        {/* ─── Right: 1/3 wide ─── */}
        <div className="space-y-4">

          {/* Appointment + Walkthrough */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Appointment</h2>
            {lead.appointment_at ? (
              <div className="space-y-1.5">
                <p className="text-sm text-green-400 font-medium">{formatDate(lead.appointment_at)}</p>
                <div className="flex gap-3 text-xs text-gray-500">
                  {lead.appt_day_before_sent && <span>D-1 reminder ✓</span>}
                  {lead.appt_morning_sent && <span>AM reminder ✓</span>}
                  {lead.appt_no_show_sent && <span className="text-yellow-400">No-show sent</span>}
                </div>
              </div>
            ) : (
              <p className="text-gray-600 text-xs">No appointment scheduled</p>
            )}
            <div className="mt-3 pt-3 border-t border-gray-700">
              <p className="text-xs text-gray-500 mb-1">Walkthrough</p>
              <WalkthroughBadge state={lead.walkthrough_state} />
              {lead.walkthrough_notes && (
                <p className="text-xs text-gray-400 mt-1 italic">{lead.walkthrough_notes}</p>
              )}
              {lead.walkthrough_completed_at && (
                <p className="text-xs text-gray-500 mt-0.5">{formatDate(lead.walkthrough_completed_at)}</p>
              )}
              <form action={`${API}/api/workflow/leads/${id}/walkthrough`} method="POST" className="mt-2">
                <select name="state" className="text-xs bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600">
                  <option value="none">none</option>
                  <option value="scheduled">scheduled</option>
                  <option value="completed">completed</option>
                  <option value="missed">missed</option>
                  <option value="cancelled">cancelled</option>
                </select>
                <button type="submit" className="ml-2 text-xs px-2 py-1 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                  Update
                </button>
              </form>
            </div>
          </section>

          {/* Active Followup Tasks */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Active Tasks
              {followups.length > 0 && (
                <span className="text-yellow-500 ml-2 font-normal normal-case">({followups.length})</span>
              )}
            </h2>
            {followups.length === 0 ? (
              <p className="text-gray-600 text-xs">No pending tasks</p>
            ) : (
              <div className="space-y-2">
                {followups.map((f: any) => (
                  <div key={f.id} className="border border-gray-700 rounded p-2.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <PriorityBadge priority={f.priority} />
                      <span className="text-xs text-gray-300 capitalize">{f.followup_type?.replace(/_/g, ' ')}</span>
                      {f.created_by && f.created_by !== 'system' && (
                        <span className="text-xs text-blue-400">{f.created_by}</span>
                      )}
                    </div>
                    {f.notes && <p className="text-xs text-gray-400 mt-1 italic">{f.notes}</p>}
                    {f.scheduled_at && (
                      <p className="text-xs text-blue-300 mt-1">{formatDate(f.scheduled_at)}</p>
                    )}
                    <div className="flex gap-3 mt-2">
                      <form action={`${API}/api/workflow/followups/${f.id}/complete`} method="POST">
                        <button type="submit" className="text-xs text-green-400 hover:text-green-300">✓ Done</button>
                      </form>
                      <form action={`${API}/api/workflow/followups/${f.id}/cancel`} method="POST">
                        <button type="submit" className="text-xs text-gray-500 hover:text-gray-400">× Cancel</button>
                      </form>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <form action={`${API}/api/workflow/leads/${id}/followup`} method="POST" className="mt-3 pt-3 border-t border-gray-700">
              <div className="flex gap-2">
                <select name="followup_type" className="flex-1 text-xs bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600">
                  <option value="call">call</option>
                  <option value="walkthrough">walkthrough</option>
                  <option value="sms">sms</option>
                  <option value="email">email</option>
                  <option value="other">other</option>
                </select>
                <select name="priority" className="text-xs bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600">
                  <option value="high">high</option>
                  <option value="medium">medium</option>
                  <option value="low">low</option>
                </select>
              </div>
              <button type="submit" className="mt-2 w-full text-xs py-1.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                + Add Task
              </button>
            </form>
          </section>

          {/* Offers */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Offers
              {offers.length > 0 && (
                <span className="text-gray-500 ml-2 font-normal normal-case">({offers.length})</span>
              )}
            </h2>
            {offers.length === 0 ? (
              <p className="text-gray-600 text-xs">No offers yet</p>
            ) : (
              <div className="space-y-2 mb-3">
                {offers.map((offer: any) => (
                  <div key={offer.id} className="border border-gray-700 rounded p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-gray-200">{formatCurrency(offer.offer_amount)}</span>
                      <OfferStatusBadge status={offer.offer_status} />
                    </div>
                    <div className="text-xs text-gray-500 mt-1 space-y-0.5">
                      {offer.arv_used && <p>ARV used: {formatCurrency(offer.arv_used)}</p>}
                      {offer.mao_calculated && <p>MAO calc: {formatCurrency(offer.mao_calculated)}</p>}
                      {offer.repair_estimate > 0 && <p>Repairs: {formatCurrency(offer.repair_estimate)}</p>}
                    </div>
                    {offer.notes && <p className="text-xs text-gray-400 mt-1 italic">{offer.notes}</p>}
                    <p className="text-xs text-gray-600 mt-1">{timeAgo(offer.created_at)}</p>
                  </div>
                ))}
              </div>
            )}
            {/* Quick offer creation from existing ARV */}
            {maoCents != null && (
              <form action={`${API}/api/offers`} method="POST" className="pt-3 border-t border-gray-700">
                <input type="hidden" name="lead_id" value={id} />
                <div className="space-y-2">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Offer Amount</p>
                    <input
                      type="number"
                      name="offer_amount"
                      defaultValue={Math.round(maoCents / 100)}
                      className="w-full bg-gray-700 text-gray-200 text-sm rounded px-2 py-1 border border-gray-600 focus:border-green-500 focus:outline-none"
                      placeholder="Amount in dollars"
                    />
                    <p className="text-xs text-gray-600 mt-0.5">MAO: {formatCurrency(maoCents)}</p>
                  </div>
                  <input type="hidden" name="arv_used" value={arvCents ?? ''} />
                  <button type="submit" className="w-full text-xs py-1.5 bg-green-900/40 text-green-300 rounded hover:bg-green-900/60">
                    + Draft Offer
                  </button>
                </div>
              </form>
            )}
          </section>

          {/* Set Workflow State */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Set Workflow State</h2>
            <form action={`${API}/api/workflow/leads/${id}/state`} method="POST">
              <select name="state" className="w-full text-xs bg-gray-700 text-gray-300 rounded px-2 py-1.5 border border-gray-600 mb-2">
                {[
                  'new_lead', 'active_contact', 'followup_required',
                  'appointment_pending', 'appointment_confirmed',
                  'negotiation', 'under_review', 'dead_lead', 'closed',
                ].map(s => (
                  <option key={s} value={s} selected={s === lead.workflow_state}>{s.replace(/_/g, ' ')}</option>
                ))}
              </select>
              <input
                type="text"
                name="notes"
                placeholder="Optional notes..."
                className="w-full bg-gray-700 text-gray-300 text-xs rounded px-2 py-1 border border-gray-600 focus:border-blue-500 focus:outline-none mb-2"
              />
              <button type="submit" className="w-full text-xs py-1.5 bg-blue-900/40 text-blue-300 rounded hover:bg-blue-900/60">
                Apply State
              </button>
            </form>
          </section>

          {/* Recent Events */}
          {events.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Activity</h2>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {events.map((ev: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="text-gray-600 w-14 shrink-0 text-right">{timeAgo(ev.created_at)}</span>
                    <span className="font-mono text-blue-300 truncate">{ev.event_type}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Distress Indicators */}
          {latestCall && Array.isArray(latestCall.distress_indicators) && latestCall.distress_indicators.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Distress Signals</h2>
              <div className="flex flex-wrap gap-1">
                {latestCall.distress_indicators.map((d: string, i: number) => (
                  <span key={i} className="bg-red-900/40 text-red-300 text-xs px-2 py-0.5 rounded">{d}</span>
                ))}
              </div>
            </section>
          )}

          {/* Objections */}
          {latestCall && Array.isArray(latestCall.objections) && latestCall.objections.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Objections Raised</h2>
              <ul className="space-y-1">
                {latestCall.objections.map((o: string, i: number) => (
                  <li key={i} className="text-xs text-gray-300">• {o}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Owner Info */}
          {(prop.owner_name || lead.owner_phone || lead.owner_email) && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Owner</h2>
              <div className="space-y-1 text-xs">
                {prop.owner_name && <p className="text-gray-200">{prop.owner_name}</p>}
                {lead.owner_phone && (
                  <p className="text-gray-400 font-mono">{lead.owner_phone}</p>
                )}
                {lead.owner_email && (
                  <p className="text-gray-400">{lead.owner_email}</p>
                )}
              </div>
            </section>
          )}

        </div>
      </div>
    </main>
  )
}
