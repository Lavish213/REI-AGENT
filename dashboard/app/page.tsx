import Link from 'next/link'
export const dynamic = 'force-dynamic'

import { backendFetch } from '@/lib/backend'
import { getSupabase } from '@/lib/supabase'
import LiveActivity from '@/components/LiveActivity'


function todayISOStart() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

async function fetchPipeline() {
  try {
    const res = await backendFetch(`/api/workflow/pipeline`, { cache: 'no-store' })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function MorningBriefingPage() {
  const todayStart = todayISOStart()

  const [
    hotLeadsRes,
    followupNeededRes,
    callsTodayRes,
    apptTodayRes,
    recentCallsRes,
    pipelineData,
    liveEventsRes,
  ] = await Promise.all([
    getSupabase()
      .from('leads')
      .select('id', { count: 'exact', head: true })
      .eq('is_hot_lead', true)
      .neq('stage', 'dead'),
    getSupabase()
      .from('followups')
      .select('id', { count: 'exact', head: true })
      .eq('status', 'pending'),
    getSupabase()
      .from('calls')
      .select('id', { count: 'exact', head: true })
      .gte('created_at', todayStart),
    getSupabase()
      .from('leads')
      .select('id', { count: 'exact', head: true })
      .eq('stage', 'walkthrough_booked'),
    getSupabase()
      .from('calls')
      .select('id, created_at, call_disposition, score_overall, call_summary, leads(address)')
      .order('created_at', { ascending: false })
      .limit(8),
    fetchPipeline(),
    getSupabase()
      .from('call_events')
      .select('id, event_type, payload, created_at, lead_id')
      .order('created_at', { ascending: false })
      .limit(10),
  ])

  const hotCount = hotLeadsRes.count ?? 0
  const followupCount = followupNeededRes.count ?? 0
  const callsTodayCount = callsTodayRes.count ?? 0
  const apptCount = apptTodayRes.count ?? 0
  const recentCalls = recentCallsRes.data ?? []
  const pipeline: Record<string, number> = pipelineData?.pipeline ?? {}
  const liveEvents = liveEventsRes.data ?? []

  const dispColor: Record<string, string> = {
    HOT: 'text-red-400', WARM: 'text-yellow-400',
    COLD: 'text-blue-300', DEAD: 'text-gray-500',
  }

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Operations</h1>
        <div className="flex gap-3 text-sm">
          <Link href="/live" className="text-green-400 hover:underline">Live →</Link>
          <Link href="/analytics" className="text-blue-400 hover:underline">Analytics →</Link>
          <Link href="/workflow" className="text-blue-400 hover:underline">Workflow →</Link>
          <Link href="/calls" className="text-blue-400 hover:underline">Calls →</Link>
          <Link href="/leads" className="text-blue-400 hover:underline">Leads →</Link>
          <Link href="/queue" className="text-blue-400 hover:underline">Queue →</Link>
        </div>
      </div>

      {/* Operational stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs text-gray-400 mb-1">Hot Leads</p>
          <p className={`text-3xl font-bold ${hotCount > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {hotCount}
          </p>
          <p className="text-xs text-gray-600 mt-1">need contact now</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs text-gray-400 mb-1">Pending Followups</p>
          <p className={`text-3xl font-bold ${followupCount > 0 ? 'text-yellow-400' : 'text-gray-500'}`}>
            {followupCount}
          </p>
          <p className="text-xs text-gray-600 mt-1">in queue</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs text-gray-400 mb-1">Calls Today</p>
          <p className="text-3xl font-bold text-green-400">{callsTodayCount}</p>
          <p className="text-xs text-gray-600 mt-1">since midnight</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs text-gray-400 mb-1">Walkthroughs Booked</p>
          <p className={`text-3xl font-bold ${apptCount > 0 ? 'text-green-400' : 'text-gray-500'}`}>
            {apptCount}
          </p>
          <p className="text-xs text-gray-600 mt-1">pending visits</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Workflow pipeline */}
        {Object.keys(pipeline).length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Workflow Pipeline
            </h2>
            <div className="bg-gray-800 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <tbody>
                  {Object.entries(pipeline).map(([state, count]: [string, number]) => (
                    <tr key={state} className="border-b border-gray-700/50 last:border-0">
                      <td className="px-4 py-2 text-gray-400 capitalize">{state.replace(/_/g, ' ')}</td>
                      <td className="px-4 py-2 text-right">
                        <span className={`font-mono font-semibold ${
                          count > 0 ? (state === 'dead_lead' ? 'text-gray-600' : 'text-white') : 'text-gray-700'
                        }`}>{count}</span>
                      </td>
                      <td className="px-4 py-2 w-32">
                        <div className="bg-gray-700 rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${
                              state === 'dead_lead' ? 'bg-gray-600' :
                              state === 'closed' ? 'bg-green-500' :
                              state.includes('appointment') ? 'bg-green-400' :
                              state === 'hot_lead' ? 'bg-red-500' : 'bg-blue-500'
                            }`}
                            style={{ width: `${Math.min(100, (count / Math.max(1, Math.max(...Object.values(pipeline) as number[]))) * 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent calls */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Recent Calls
          </h2>
          <div className="space-y-2">
            {recentCalls.length === 0 ? (
              <div className="bg-gray-800 rounded-lg p-4 text-center text-gray-600 text-sm">
                No calls yet today
              </div>
            ) : (
              recentCalls.map((call) => {
                const address = (Array.isArray(call.leads) ? call.leads[0] : call.leads)?.address ?? '—'
                const disp = call.call_disposition
                const qa = call.score_overall
                return (
                  <div key={call.id} className="bg-gray-800 rounded-lg p-3">
                    <div className="flex items-center gap-3">
                      <span className="flex-1 text-sm truncate">{address}</span>
                      <span className={`text-xs ${dispColor[disp] ?? 'text-gray-500'}`}>
                        {disp ?? '—'}
                      </span>
                      {qa != null && (
                        <span className={`text-xs font-mono font-semibold ${qa >= 8 ? 'text-green-400' : qa >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>
                          {qa.toFixed(1)}
                        </span>
                      )}
                      <a href={`/calls/${call.id}`} className="text-xs text-blue-400 hover:underline shrink-0">
                        →
                      </a>
                    </div>
                    {call.call_summary && (
                      <p className="text-xs text-gray-500 mt-1 italic leading-tight line-clamp-1">
                        {call.call_summary}
                      </p>
                    )}
                  </div>
                )
              })
            )}
          </div>
          <Link href="/calls" className="text-xs text-blue-400 hover:underline mt-2 inline-block">
            View all calls →
          </Link>
        </section>
      </div>

      <div className="mt-6">
        <LiveActivity initialEvents={liveEvents} />
      </div>
    </main>
  )
}
