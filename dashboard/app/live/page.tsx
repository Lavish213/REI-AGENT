import { supabase } from '@/lib/supabase'
import LiveActivity from '@/components/LiveActivity'

const API = process.env.NEXT_PUBLIC_API_URL || ''

async function fetchLiveCalls() {
  try {
    const res = await fetch(`${API}/api/live/calls`, { cache: 'no-store' })
    if (!res.ok) return { active_count: 0, calls: [] }
    return res.json()
  } catch {
    return { active_count: 0, calls: [] }
  }
}

function elapsed(startedAt: string | null): string {
  if (!startedAt) return '—'
  const ms = Date.now() - new Date(startedAt).getTime()
  const secs = Math.floor(ms / 1000)
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default async function LivePage() {
  const [liveData, recentEventsRes] = await Promise.all([
    fetchLiveCalls(),
    supabase
      .from('call_events')
      .select('id, event_type, payload, created_at, lead_id')
      .order('created_at', { ascending: false })
      .limit(15),
  ])

  const activeCalls = liveData.calls ?? []
  const recentEvents = recentEventsRes.data ?? []

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Live Control Center</h1>
          <p className="text-xs text-gray-500 mt-0.5">Refresh page to update active calls · Events stream live</p>
        </div>
        <div className="flex gap-3 text-sm">
          <a href="/" className="text-blue-400 hover:underline">← Operations</a>
          <a href="/calls" className="text-blue-400 hover:underline">Call History →</a>
        </div>
      </div>

      {/* Active calls */}
      <section className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
            Active Calls
          </h2>
          <span className={`text-sm font-mono font-semibold ${activeCalls.length > 0 ? 'text-green-400' : 'text-gray-600'}`}>
            {activeCalls.length}
          </span>
          {activeCalls.length > 0 && (
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          )}
        </div>

        {activeCalls.length === 0 ? (
          <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-600 text-sm">
            No active calls right now
          </div>
        ) : (
          <div className="space-y-2">
            {activeCalls.map((call: any) => (
              <div key={call.call_sid} className="bg-gray-800 rounded-lg p-4">
                <div className="flex items-center gap-4">
                  <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">
                        {call.address ? `${call.address}, ${call.city}` : 'Unknown address'}
                      </span>
                      {call.boss_mode && (
                        <span className="text-xs px-1.5 py-0.5 bg-purple-900/40 text-purple-300 rounded">
                          Boss Mode
                        </span>
                      )}
                      {call.spanish && (
                        <span className="text-xs px-1.5 py-0.5 bg-blue-900/40 text-blue-300 rounded">
                          ES
                        </span>
                      )}
                      {call.metrics?.phase && (
                        <span className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded font-mono">
                          {call.metrics.phase}
                        </span>
                      )}
                      {call.metrics?.seller_energy && call.metrics.seller_energy !== 'calm' && (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          call.metrics.seller_energy === 'motivated' ? 'bg-green-900/40 text-green-300' :
                          call.metrics.seller_energy === 'emotional' ? 'bg-yellow-900/40 text-yellow-300' :
                          call.metrics.seller_energy === 'skeptical' ? 'bg-orange-900/40 text-orange-300' :
                          call.metrics.seller_energy === 'rushed' ? 'bg-red-900/40 text-red-300' :
                          'bg-gray-700 text-gray-400'
                        }`}>
                          {call.metrics.seller_energy}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
                      {call.owner_first_name && <span>{call.owner_first_name}</span>}
                      {call.lead_stage && <span>Stage: {call.lead_stage}</span>}
                      {call.metrics?.turn_count != null && (
                        <span>Turn {call.metrics.turn_count}</span>
                      )}
                      {call.metrics?.disposition && (
                        <span className={
                          call.metrics.disposition === 'HOT' ? 'text-red-400' :
                          call.metrics.disposition === 'WARM' ? 'text-yellow-400' :
                          call.metrics.disposition === 'COLD' ? 'text-blue-300' : 'text-gray-500'
                        }>
                          {call.metrics.disposition}
                        </span>
                      )}
                      {call.metrics?.situation_label && call.metrics.situation_label !== 'unknown' && (
                        <span className="text-purple-400">{call.metrics.situation_label.replace(/_/g, ' ')}</span>
                      )}
                    </div>
                    {call.metrics?.objections_raised?.length > 0 && (
                      <div className="text-xs text-orange-400/70 mt-0.5">
                        Objections: {call.metrics.objections_raised.join(', ')}
                      </div>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-mono text-green-400">
                      {elapsed(call.started_at)}
                    </div>
                    <div className="text-xs text-gray-600 mt-0.5">elapsed</div>
                  </div>
                  {call.lead_id && (
                    <a
                      href={`/leads/${call.lead_id}`}
                      className="text-xs text-blue-400 hover:underline shrink-0"
                    >
                      Lead →
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Live activity feed */}
      <LiveActivity initialEvents={recentEvents as any} />
    </main>
  )
}
