import type { OpsRow } from '@/lib/types'
export const dynamic = 'force-dynamic'

import { backendFetch } from '@/lib/backend'

async function fetchWorkflow(path: string) {
  try {
    const res = await backendFetch(`/api${path}`, { cache: 'no-store' })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

function PriorityBadge({ priority }: { priority?: string | null }) {
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

function StateBadge({ state }: { state?: string | null }) {
  if (!state) return <span className="text-gray-500 text-xs">—</span>
  const cls: Record<string, string> = {
    new_lead: 'bg-gray-700 text-gray-300',
    active_contact: 'bg-blue-800 text-blue-200',
    followup_required: 'bg-yellow-800 text-yellow-200',
    appointment_pending: 'bg-orange-800 text-orange-200',
    appointment_confirmed: 'bg-green-800 text-green-200',
    negotiation: 'bg-purple-800 text-purple-200',
    under_review: 'bg-indigo-800 text-indigo-200',
    dead_lead: 'bg-gray-700 text-gray-500',
    closed: 'bg-green-900 text-green-300',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${cls[state] ?? 'bg-gray-700 text-gray-300'}`}>
      {state.replace(/_/g, ' ')}
    </span>
  )
}

function EventRow({ ev }: { ev: OpsRow }) {
  const ago = ev.created_at ? new Date(ev.created_at).toLocaleString('en-US') : '—'

  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-gray-800 last:border-0">
      <span className="text-gray-600 text-xs w-16 shrink-0 text-right">{ago}</span>
      <span className={`text-xs font-mono text-gray-400`}>
        {ev.event_type}
      </span>
      {ev.payload?.state && (
        <StateBadge state={ev.payload.state} />
      )}
      {ev.payload?.priority && (
        <PriorityBadge priority={ev.payload.priority} />
      )}
    </div>
  )
}

export default async function WorkflowPage() {
  const [
    activityData,
    followupData,
    hotLeadsData,
    appointmentsData,
    pipelineData,
  ] = await Promise.all([
    fetchWorkflow('/workflow/activity?limit=30'),
    fetchWorkflow('/workflow/followups?limit=20'),
    fetchWorkflow('/workflow/hot-leads?limit=15'),
    fetchWorkflow('/workflow/appointments?limit=10'),
    fetchWorkflow('/workflow/pipeline'),
  ])

  const events: OpsRow[] = activityData?.events ?? []
  const followups: OpsRow[] = followupData?.followups ?? []
  const hotLeads: OpsRow[] = hotLeadsData?.leads ?? []
  const appointments: OpsRow[] = appointmentsData?.appointments ?? []
  const pipeline: Record<string, number> = pipelineData?.pipeline ?? {}

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Workflow Operations</h1>
        <span className="text-xs text-gray-500">Live — refreshes on load</span>
      </div>

      {/* Pipeline state bar */}
      <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-9 gap-2 mb-8">
        {Object.entries(pipeline).map(([state, count]: [string, number]) => (
          <div key={state} className="bg-gray-800 rounded-lg p-3 text-center">
            <p className={`text-2xl font-bold font-mono ${count > 0 ? 'text-white' : 'text-gray-600'}`}>
              {count}
            </p>
            <p className="text-gray-500 text-xs mt-0.5 leading-tight">{state.replace(/_/g, ' ')}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left: Activity feed */}
        <div className="space-y-4">
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Activity Feed
              <span className="text-gray-600 ml-2 font-normal normal-case">({events.length})</span>
            </h2>
            {events.length === 0 ? (
              <p className="text-gray-600 text-xs">No recent events</p>
            ) : (
              <div className="max-h-80 overflow-y-auto">
                {events.map((ev) => <EventRow key={ev.id} ev={ev} />)}
              </div>
            )}
          </section>

          {/* Appointment queue */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Appointments
              <span className="text-gray-600 ml-2 font-normal normal-case">({appointments.length})</span>
            </h2>
            {appointments.length === 0 ? (
              <p className="text-gray-600 text-xs">No upcoming appointments</p>
            ) : (
              <div className="space-y-2">
                {appointments.map((appt) => {
                  const prop = appt.properties ?? {}
                  const apptDate = appt.appointment_at
                    ? new Date(appt.appointment_at).toLocaleString('en-US', {
                        month: 'short', day: 'numeric',
                        hour: 'numeric', minute: '2-digit',
                      })
                    : '—'
                  return (
                    <div key={appt.id} className="border border-gray-700 rounded p-2">
                      <p className="text-sm text-white truncate">{prop.address ?? '—'}</p>
                      <p className="text-xs text-green-400 mt-0.5">{apptDate}</p>
                      <div className="flex gap-2 mt-1">
                        {appt.appt_day_before_sent && <span className="text-xs text-gray-500">D-1 ✓</span>}
                        {appt.appt_morning_sent && <span className="text-xs text-gray-500">AM ✓</span>}
                        {appt.appt_no_show_sent && <span className="text-xs text-yellow-500">No-show</span>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>

        {/* Center: Hot leads */}
        <div>
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Hot Leads
              <span className="text-red-500 ml-2 font-normal normal-case">({hotLeads.length})</span>
            </h2>
            {hotLeads.length === 0 ? (
              <p className="text-gray-600 text-xs">No hot leads</p>
            ) : (
              <div className="space-y-2">
                {hotLeads.map((lead) => {
                  const prop = lead.properties ?? {}
                  return (
                    <div key={lead.id} className="border border-red-900/40 rounded-lg p-3 bg-red-950/20">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm text-white truncate flex-1">
                          {prop.address ?? '—'}
                        </p>
                        <StateBadge state={lead.workflow_state} />
                      </div>
                      <div className="flex items-center gap-3 mt-1.5">
                        {lead.motivation_level != null && (
                          <span className="text-xs text-red-400">
                            Motiv {lead.motivation_level}/10
                          </span>
                        )}
                        {lead.timeline_urgency && (
                          <span className="text-xs text-yellow-400 capitalize">
                            {lead.timeline_urgency}
                          </span>
                        )}
                        {lead.followup_urgency != null && (
                          <span className="text-xs text-gray-400">
                            Urgency {lead.followup_urgency}
                          </span>
                        )}
                      </div>
                      {lead.call_summary && (
                        <p className="text-xs text-gray-500 mt-1.5 italic leading-tight line-clamp-2">
                          {lead.call_summary}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>

        {/* Right: Followup queue */}
        <div>
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Followup Queue
              <span className="text-yellow-500 ml-2 font-normal normal-case">({followups.length} pending)</span>
            </h2>
            {followups.length === 0 ? (
              <p className="text-gray-600 text-xs">No pending followups</p>
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {followups.map((f) => {
                  const lead = f.leads ?? {}
                  return (
                    <div key={f.id} className="border border-gray-700 rounded-lg p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white truncate">
                            {lead.address ?? f.lead_id?.slice(0, 8) ?? '—'}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <PriorityBadge priority={f.priority} />
                            <span className="text-xs text-gray-500 capitalize">
                              {f.followup_type}
                            </span>
                            {f.created_by && f.created_by !== 'system' && (
                              <span className="text-xs text-blue-400">{f.created_by}</span>
                            )}
                          </div>
                        </div>
                        <StateBadge state={lead.workflow_state} />
                      </div>
                      {f.notes && (
                        <p className="text-xs text-gray-400 mt-1.5 italic leading-tight">{f.notes}</p>
                      )}
                      {f.scheduled_at && (
                        <p className="text-xs text-blue-300 mt-1">
                          Scheduled: {new Date(f.scheduled_at).toLocaleString('en-US', {
                            month: 'short', day: 'numeric',
                            hour: 'numeric', minute: '2-digit',
                          })}
                        </p>
                      )}
                      <div className="flex gap-2 mt-2">
                        <form action={`/api/backend/api/workflow/followups/${f.id}/complete`} method="POST">
                          <button type="submit" className="text-xs text-green-400 hover:text-green-300">
                            ✓ Done
                          </button>
                        </form>
                        <form action={`/api/backend/api/workflow/followups/${f.id}/cancel`} method="POST">
                          <button type="submit" className="text-xs text-gray-500 hover:text-gray-400">
                            × Cancel
                          </button>
                        </form>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}
