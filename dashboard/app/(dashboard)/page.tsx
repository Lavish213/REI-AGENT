import { supabase } from '@/lib/supabase'

function formatCurrency(cents: number | null) {
  if (cents == null) return '—'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function todayISOStart() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

export default async function MorningBriefingPage() {
  const todayStart = todayISOStart()

  // Fetch all data in parallel
  const [
    activeLeadsRes,
    hotLeadsRes,
    callsTodayRes,
    topDistressRes,
    recentCallsRes,
  ] = await Promise.all([
    supabase
      .from('leads')
      .select('id', { count: 'exact', head: true })
      .neq('status', 'dead'),
    supabase
      .from('leads')
      .select('id', { count: 'exact', head: true })
      .gte('composite_score', 85)
      .neq('status', 'dead'),
    supabase
      .from('calls')
      .select('id', { count: 'exact', head: true })
      .gte('created_at', todayStart),
    supabase
      .from('leads')
      .select('id, address, distress_score, arv, mao')
      .neq('status', 'dead')
      .order('distress_score', { ascending: false })
      .limit(5),
    supabase
      .from('calls')
      .select('id, created_at, disposition, qa_score, transcript, leads(address)')
      .order('created_at', { ascending: false })
      .limit(5),
  ])

  const activeCount = activeLeadsRes.count ?? 0
  const hotCount = hotLeadsRes.count ?? 0
  const callsTodayCount = callsTodayRes.count ?? 0
  const topDistress = topDistressRes.data ?? []
  const recentCalls = recentCallsRes.data ?? []

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <h1 className="text-2xl font-bold mb-6">Morning Briefing</h1>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-sm text-gray-400 mb-1">Active Leads</p>
          <p className="text-3xl font-bold">{activeCount}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-sm text-gray-400 mb-1">Hot Leads Today (score ≥ 85)</p>
          <p className="text-3xl font-bold text-yellow-400">{hotCount}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-sm text-gray-400 mb-1">Calls Handled Today</p>
          <p className="text-3xl font-bold text-green-400">{callsTodayCount}</p>
        </div>
      </div>

      {/* Top 5 Distress Leads */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold mb-3 text-gray-200">Top 5 Leads by Distress Score</h2>
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-700">
                <th className="px-4 py-3">Address</th>
                <th className="px-4 py-3 text-right">Distress Score</th>
                <th className="px-4 py-3 text-right">ARV</th>
                <th className="px-4 py-3 text-right">MAO</th>
              </tr>
            </thead>
            <tbody>
              {topDistress.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-500">No leads found</td>
                </tr>
              ) : (
                topDistress.map((lead: any) => (
                  <tr key={lead.id} className="border-b border-gray-700 hover:bg-gray-750">
                    <td className="px-4 py-3">{lead.address ?? '—'}</td>
                    <td className="px-4 py-3 text-right font-mono">
                      <span className={`font-semibold ${
                        lead.distress_score >= 80 ? 'text-red-400' :
                        lead.distress_score >= 60 ? 'text-yellow-400' : 'text-gray-300'
                      }`}>
                        {lead.distress_score ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300">{formatCurrency(lead.arv)}</td>
                    <td className="px-4 py-3 text-right font-mono text-green-400">{formatCurrency(lead.mao)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Recent Calls */}
      <section>
        <h2 className="text-lg font-semibold mb-3 text-gray-200">Recent Calls</h2>
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-700">
                <th className="px-4 py-3">Address</th>
                <th className="px-4 py-3">Disposition</th>
                <th className="px-4 py-3 text-right">QA Score</th>
              </tr>
            </thead>
            <tbody>
              {recentCalls.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">No calls found</td>
                </tr>
              ) : (
                recentCalls.map((call: any) => {
                  const address = call.leads?.address ?? '—'
                  const qa = call.qa_score
                  const qaColor =
                    qa == null ? 'text-gray-500' :
                    qa >= 80 ? 'text-green-400' :
                    qa >= 60 ? 'text-yellow-400' : 'text-red-400'
                  return (
                    <tr key={call.id} className="border-b border-gray-700 hover:bg-gray-750">
                      <td className="px-4 py-3">{address}</td>
                      <td className="px-4 py-3 text-gray-300">{call.disposition ?? '—'}</td>
                      <td className={`px-4 py-3 text-right font-mono font-semibold ${qaColor}`}>
                        {qa != null ? qa : '—'}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}
