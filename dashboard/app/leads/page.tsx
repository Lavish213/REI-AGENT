import { supabase } from '@/lib/supabase'

function formatCurrency(cents: number | null) {
  if (cents == null) return '—'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const stageBadge: Record<string, string> = {
  new: 'bg-blue-600 text-blue-100',
  contacted: 'bg-yellow-600 text-yellow-100',
  offer_made: 'bg-orange-600 text-orange-100',
  walkthrough_booked: 'bg-green-600 text-green-100',
  under_contract: 'bg-purple-600 text-purple-100',
  closed: 'bg-green-800 text-green-100',
  dead: 'bg-gray-600 text-gray-300',
}

export default async function LeadsPage() {
  const { data: leads, error } = await supabase
    .from('leads')
    .select('id, address, distress_score, composite_score, arv, mao, stage, status, last_contact, callable, motivation_level, timeline_urgency, followup_urgency, is_hot_lead, call_summary')
    .order('followup_urgency', { ascending: false })
    .limit(100)

  const rows = leads ?? []

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Leads</h1>
        <span className="text-sm text-gray-400">{rows.length} shown (top 100 by distress score)</span>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg p-4 mb-6">
          Error loading leads: {error.message}
        </div>
      )}

      <div className="bg-gray-800 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-700">
              <th className="px-4 py-3">Address</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3 text-right">ARV</th>
              <th className="px-4 py-3 text-right">MAO</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3 text-center">Motiv</th>
              <th className="px-4 py-3">Timeline</th>
              <th className="px-4 py-3 text-center">Urgency</th>
              <th className="px-4 py-3 text-center">Callable</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-gray-500">No leads found</td>
              </tr>
            ) : (
              rows.map((lead: any) => {
                const stage = lead.stage ?? lead.status ?? 'new'
                const badgeClass = stageBadge[stage] ?? 'bg-gray-600 text-gray-300'
                const score = lead.distress_score ?? lead.composite_score
                const scoreColor =
                  score == null ? 'text-gray-500' :
                  score >= 80 ? 'text-red-400' :
                  score >= 60 ? 'text-yellow-400' : 'text-gray-300'

                const motivation = lead.motivation_level
                const motivColor = motivation == null ? 'text-gray-500' :
                  motivation >= 8 ? 'text-red-400' :
                  motivation >= 6 ? 'text-yellow-400' : 'text-gray-400'

                const timeline = lead.timeline_urgency
                const timelineColor: Record<string, string> = {
                  immediate: 'text-red-400', weeks: 'text-yellow-400',
                  months: 'text-blue-300', unknown: 'text-gray-500',
                }

                const urgency = lead.followup_urgency
                const urgencyColor = urgency == null ? 'text-gray-500' :
                  urgency >= 8 ? 'text-red-400' :
                  urgency >= 5 ? 'text-yellow-400' : 'text-gray-400'

                return (
                  <>
                    <tr key={lead.id} className="border-b border-gray-700/50 hover:bg-gray-750">
                      <td className="px-4 py-2 max-w-xs truncate">
                        {lead.is_hot_lead && <span className="text-red-400 text-xs mr-1">🔥</span>}
                        {lead.address ?? '—'}
                      </td>
                      <td className={`px-4 py-2 text-right font-mono font-semibold ${scoreColor}`}>
                        {score ?? '—'}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-gray-300">{formatCurrency(lead.arv)}</td>
                      <td className="px-4 py-2 text-right font-mono text-green-400">{formatCurrency(lead.mao)}</td>
                      <td className="px-4 py-2">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${badgeClass}`}>
                          {stage.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className={`px-4 py-2 text-center font-mono font-semibold ${motivColor}`}>
                        {motivation ?? '—'}
                      </td>
                      <td className={`px-4 py-2 text-xs capitalize ${timelineColor[timeline] ?? 'text-gray-500'}`}>
                        {timeline ?? '—'}
                      </td>
                      <td className={`px-4 py-2 text-center font-mono font-semibold ${urgencyColor}`}>
                        {urgency ?? '—'}
                      </td>
                      <td className="px-4 py-2 text-center">
                        {lead.callable === false ? (
                          <span className="text-red-400 text-xs">No</span>
                        ) : lead.callable === true ? (
                          <span className="text-green-400 text-xs">Yes</span>
                        ) : (
                          <span className="text-gray-500 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <a href={`/leads/${lead.id}`} className="text-xs text-blue-400 hover:underline">View →</a>
                      </td>
                    </tr>
                    {lead.call_summary && (
                      <tr key={`${lead.id}-summary`} className="border-b border-gray-700/30">
                        <td colSpan={10} className="px-4 pb-2 text-xs text-gray-500 italic">{lead.call_summary}</td>
                      </tr>
                    )}
                  </>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </main>
  )
}
