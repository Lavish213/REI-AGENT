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
    .select('id, created_at, duration_seconds, disposition, qa_score, transcript, lead_id, leads(address)')
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
          const qa = call.qa_score
          const qaColor =
            qa == null ? 'text-gray-500' :
            qa >= 80 ? 'text-green-400' :
            qa >= 60 ? 'text-yellow-400' : 'text-red-400'

          const address = call.leads?.address ?? '—'
          const hasTranscript = !!call.transcript && call.transcript.trim().length > 0

          return (
            <details
              key={call.id}
              className="bg-gray-800 rounded-lg group open:ring-1 open:ring-gray-600"
            >
              <summary className="flex items-center gap-4 px-4 py-3 cursor-pointer list-none select-none hover:bg-gray-750 rounded-lg">
                {/* Expand icon */}
                <span className="text-gray-500 group-open:rotate-90 transition-transform text-xs">▶</span>

                {/* Date */}
                <span className="text-gray-400 text-sm w-44 shrink-0">{formatDate(call.created_at)}</span>

                {/* Address */}
                <span className="flex-1 truncate font-medium">{address}</span>

                {/* Duration */}
                <span className="text-gray-400 text-sm w-16 text-right font-mono">
                  {formatDuration(call.duration_seconds)}
                </span>

                {/* Disposition */}
                <span className="text-gray-300 text-sm w-32 truncate text-right">
                  {call.disposition ?? '—'}
                </span>

                {/* QA Score */}
                <span className={`text-sm font-semibold font-mono w-12 text-right ${qaColor}`}>
                  {qa != null ? qa : '—'}
                </span>

                {/* Has Transcript */}
                <span className="w-20 text-right text-xs">
                  {hasTranscript ? (
                    <span className="text-blue-400">Transcript</span>
                  ) : (
                    <span className="text-gray-600">No transcript</span>
                  )}
                </span>
              </summary>

              {/* Expanded content */}
              <div className="px-4 pb-4 pt-2 border-t border-gray-700">
                <div className="grid grid-cols-2 gap-4 text-sm mb-4">
                  <div>
                    <span className="text-gray-400">Lead ID: </span>
                    <span className="text-gray-300 font-mono">{call.lead_id ?? '—'}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">QA Score: </span>
                    <span className={`font-semibold ${qaColor}`}>{qa != null ? qa : '—'}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">Duration: </span>
                    <span className="text-gray-300">{formatDuration(call.duration_seconds)}</span>
                  </div>
                  <div>
                    <span className="text-gray-400">Disposition: </span>
                    <span className="text-gray-300">{call.disposition ?? '—'}</span>
                  </div>
                </div>

                {hasTranscript ? (
                  <div>
                    <p className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">Transcript</p>
                    <pre className="bg-gray-900 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap overflow-auto max-h-64 leading-relaxed">
                      {call.transcript}
                    </pre>
                  </div>
                ) : (
                  <p className="text-sm text-gray-600 italic">No transcript available for this call.</p>
                )}
              </div>
            </details>
          )
        })}
      </div>
    </main>
  )
}
