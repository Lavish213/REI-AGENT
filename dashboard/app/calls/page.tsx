import { supabase } from '@/lib/supabase'

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default async function CallsPage() {
  const { data: calls, error } = await supabase
    .from('calls')
    .select('id, created_at, duration_seconds, call_disposition, score_overall, call_summary, seller_name, motivation_level, followup_priority, lead_id, leads(address)')
    .order('created_at', { ascending: false })
    .limit(50)

  const rows = calls ?? []

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Calls</h1>
        <span className="text-sm text-gray-400">{rows.length} shown (latest 50)</span>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg p-4 mb-6">
          Error loading calls: {error.message}
        </div>
      )}

      <div className="space-y-2">
        {rows.length === 0 && (
          <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-500">No calls found</div>
        )}
        {rows.map((call: any) => {
          const qa = call.score_overall
          const qaColor =
            qa == null ? 'text-gray-500' :
            qa >= 8 ? 'text-green-400' :
            qa >= 6 ? 'text-yellow-400' : 'text-red-400'

          const address = call.leads?.address ?? '—'
          const disposition = call.call_disposition
          const dispColor: Record<string, string> = {
            HOT: 'text-red-400', WARM: 'text-yellow-400',
            COLD: 'text-blue-300', DEAD: 'text-gray-500',
          }
          const priorityBadge: Record<string, string> = {
            high: 'bg-red-900/40 text-red-300',
            medium: 'bg-yellow-900/40 text-yellow-300',
            low: 'bg-gray-700 text-gray-500',
          }

          return (
            <div key={call.id} className="bg-gray-800 rounded-lg">
              <div className="flex items-center gap-4 px-4 py-3">
                <span className="text-gray-400 text-sm w-44 shrink-0">{formatDate(call.created_at)}</span>
                <span className="flex-1 truncate font-medium">{address}</span>
                {call.seller_name && (
                  <span className="text-gray-400 text-sm w-24 truncate">{call.seller_name}</span>
                )}
                <span className="text-gray-400 text-sm w-16 text-right font-mono">
                  {formatDuration(call.duration_seconds)}
                </span>
                <span className={`text-sm w-16 text-right ${dispColor[disposition] ?? 'text-gray-500'}`}>
                  {disposition ?? '—'}
                </span>
                <span className={`text-sm font-semibold font-mono w-10 text-right ${qaColor}`}>
                  {qa != null ? qa.toFixed(1) : '—'}
                </span>
                {call.followup_priority && (
                  <span className={`text-xs px-2 py-0.5 rounded ${priorityBadge[call.followup_priority] ?? ''}`}>
                    {call.followup_priority}
                  </span>
                )}
                <a href={`/calls/${call.id}`} className="text-xs text-blue-400 hover:underline shrink-0">
                  View →
                </a>
              </div>

              {call.call_summary && (
                <div className="px-4 pb-3 border-t border-gray-700/50">
                  <p className="text-xs text-gray-400 mt-2 italic leading-relaxed">{call.call_summary}</p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </main>
  )
}
