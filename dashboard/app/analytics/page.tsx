const API = process.env.NEXT_PUBLIC_API_URL || ''

async function fetchAnalytics(path: string) {
  try {
    const res = await fetch(`${API}/api${path}`, { cache: 'no-store' })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

function formatCurrency(cents: number | null | undefined) {
  if (!cents) return '$0'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-700 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default async function AnalyticsPage() {
  const [workflowData, performanceData] = await Promise.all([
    fetchAnalytics('/analytics/workflow'),
    fetchAnalytics('/calls/performance/summary'),
  ])

  const workflow = workflowData ?? {}
  const perf = performanceData ?? {}

  const workflowPipeline: Record<string, number> = workflow.workflow_pipeline ?? {}
  const stagePipeline: Record<string, number> = workflow.stage_pipeline ?? {}
  const disposition30d: Record<string, number> = workflow.disposition_30d ?? {}
  const followupQueue: Record<string, number> = workflow.followup_queue ?? {}
  const offerPipeline: Record<string, number> = workflow.offer_pipeline ?? {}

  const maxWorkflow = Math.max(1, ...Object.values(workflowPipeline) as number[])
  const maxStage = Math.max(1, ...Object.values(stagePipeline) as number[])
  const maxDisp = Math.max(1, ...Object.values(disposition30d) as number[])

  const workflowStateColors: Record<string, string> = {
    new_lead: 'bg-gray-500',
    active_contact: 'bg-blue-500',
    followup_required: 'bg-yellow-500',
    appointment_pending: 'bg-orange-500',
    appointment_confirmed: 'bg-green-400',
    negotiation: 'bg-purple-500',
    under_review: 'bg-indigo-500',
    dead_lead: 'bg-gray-600',
    closed: 'bg-green-600',
  }

  const dispColors: Record<string, string> = {
    HOT: 'text-red-400',
    WARM: 'text-yellow-400',
    COLD: 'text-blue-300',
    DEAD: 'text-gray-500',
    unknown: 'text-gray-600',
  }

  return (
    <main className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold">Analytics</h1>
        <div className="flex gap-3 text-sm">
          <a href="/" className="text-blue-400 hover:underline">Ops →</a>
          <a href="/workflow" className="text-blue-400 hover:underline">Workflow →</a>
          <a href="/leads" className="text-blue-400 hover:underline">Leads →</a>
        </div>
      </div>

      {/* Headline metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
          <p className="text-xs text-gray-400 mb-1">Active Leads</p>
          <p className="text-3xl font-bold text-white">{workflow.active_leads ?? '—'}</p>
          <p className="text-xs text-gray-600 mt-1">in workflow</p>
        </div>
        <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
          <p className="text-xs text-gray-400 mb-1">Hot Leads</p>
          <p className={`text-3xl font-bold ${(workflow.hot_leads ?? 0) > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {workflow.hot_leads ?? '—'}
          </p>
          <p className="text-xs text-gray-600 mt-1">need contact now</p>
        </div>
        <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
          <p className="text-xs text-gray-400 mb-1">Calls This Week</p>
          <p className="text-3xl font-bold text-green-400">{workflow.calls_this_week ?? '—'}</p>
          <p className="text-xs text-gray-600 mt-1">last 7 days</p>
        </div>
        <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
          <p className="text-xs text-gray-400 mb-1">Appt Conversion</p>
          <p className={`text-3xl font-bold ${(workflow.conversion_rate_pct ?? 0) > 0 ? 'text-blue-400' : 'text-gray-500'}`}>
            {workflow.conversion_rate_pct != null ? `${workflow.conversion_rate_pct}%` : '—'}
          </p>
          <p className="text-xs text-gray-600 mt-1">active → appointment</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Workflow pipeline funnel */}
        <section className="lg:col-span-2">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Workflow Pipeline</h2>
          <div className="bg-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {Object.entries(workflowPipeline).map(([state, count]: [string, any]) => (
                  <tr key={state} className="border-b border-gray-700/50 last:border-0">
                    <td className="px-4 py-2.5 text-gray-400 capitalize w-44">{state.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2.5 text-right w-12">
                      <span className={`font-mono font-semibold ${
                        count > 0 ? (state === 'dead_lead' ? 'text-gray-600' : 'text-white') : 'text-gray-700'
                      }`}>{count}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <MiniBar value={count} max={maxWorkflow} color={workflowStateColors[state] ?? 'bg-gray-500'} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Right column */}
        <div className="space-y-5">

          {/* Disposition breakdown 30d */}
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Dispositions (30d)</h2>
            <div className="bg-gray-800 rounded-lg p-4 space-y-2">
              {Object.entries(disposition30d)
                .filter(([k]) => k !== 'unknown' || (disposition30d[k] ?? 0) > 0)
                .map(([disp, count]: [string, any]) => (
                <div key={disp} className="flex items-center gap-3">
                  <span className={`text-sm font-semibold w-16 ${dispColors[disp] ?? 'text-gray-400'}`}>{disp}</span>
                  <div className="flex-1">
                    <MiniBar value={count} max={maxDisp} color={
                      disp === 'HOT' ? 'bg-red-500' :
                      disp === 'WARM' ? 'bg-yellow-500' :
                      disp === 'COLD' ? 'bg-blue-500' : 'bg-gray-600'
                    } />
                  </div>
                  <span className="text-sm font-mono text-gray-300 w-8 text-right">{count}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Followup queue health */}
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Followup Queue</h2>
            <div className="bg-gray-800 rounded-lg p-4 space-y-3">
              {[
                { label: 'High', key: 'high', color: 'text-red-400' },
                { label: 'Medium', key: 'medium', color: 'text-yellow-400' },
                { label: 'Low', key: 'low', color: 'text-gray-400' },
              ].map(({ label, key, color }) => (
                <div key={key} className="flex items-center justify-between">
                  <span className={`text-sm font-semibold ${color}`}>{label}</span>
                  <span className="text-lg font-mono font-bold text-gray-200">
                    {followupQueue[key] ?? 0}
                  </span>
                </div>
              ))}
              <div className="border-t border-gray-700 pt-2 flex justify-between text-xs">
                <span className="text-gray-500">Total pending</span>
                <span className="text-gray-300 font-mono">
                  {Object.values(followupQueue).reduce((a: any, b: any) => a + b, 0)}
                </span>
              </div>
            </div>
          </section>

          {/* Offer pipeline */}
          {Object.keys(offerPipeline).length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Offer Pipeline</h2>
              <div className="bg-gray-800 rounded-lg p-4 space-y-2">
                {Object.entries(offerPipeline).map(([status, count]: [string, any]) => (
                  <div key={status} className="flex items-center justify-between text-sm">
                    <span className="text-gray-400 capitalize">{status}</span>
                    <span className="font-mono font-semibold text-gray-200">{count}</span>
                  </div>
                ))}
                {workflow.offer_pipeline_value_cents > 0 && (
                  <div className="border-t border-gray-700 pt-2 flex justify-between text-xs">
                    <span className="text-gray-500">Pipeline value</span>
                    <span className="text-green-400 font-mono">{formatCurrency(workflow.offer_pipeline_value_cents)}</span>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      </div>

      {/* Stage pipeline (legacy) */}
      {Object.keys(stagePipeline).length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Stage Pipeline</h2>
          <div className="grid grid-cols-4 sm:grid-cols-7 gap-3">
            {Object.entries(stagePipeline).map(([stage, count]: [string, any]) => (
              <div key={stage} className="bg-gray-800 rounded-lg p-3 text-center">
                <p className={`text-xl font-bold font-mono ${count > 0 && stage !== 'dead' ? 'text-white' : 'text-gray-600'}`}>
                  {count}
                </p>
                <p className="text-gray-500 text-xs mt-0.5 capitalize leading-tight">{stage.replace(/_/g, ' ')}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* QA Performance */}
      {perf.total_calls > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Agent Performance (7 days)</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
              <p className="text-xs text-gray-400">Total Calls</p>
              <p className="text-2xl font-bold text-white">{perf.total_calls}</p>
            </div>
            {perf.avg_score != null && (
              <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
                <p className="text-xs text-gray-400">Avg QA Score</p>
                <p className={`text-2xl font-bold ${perf.avg_score >= 8 ? 'text-green-400' : perf.avg_score >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {perf.avg_score.toFixed(1)}
                </p>
              </div>
            )}
            {perf.appointment_rate != null && (
              <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
                <p className="text-xs text-gray-400">Appointment Rate</p>
                <p className="text-2xl font-bold text-green-400">{Math.round(perf.appointment_rate * 100)}%</p>
              </div>
            )}
            {perf.hot_lead_rate != null && (
              <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}>
                <p className="text-xs text-gray-400">Hot Lead Rate</p>
                <p className="text-2xl font-bold text-red-400">{Math.round(perf.hot_lead_rate * 100)}%</p>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  )
}
