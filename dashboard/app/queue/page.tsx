const API = process.env.NEXT_PUBLIC_API_URL || ''

async function getQueue() {
  try {
    const res = await fetch(`${API}/api/leads/queue`, { cache: 'no-store' })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score == null) return <span className="text-gray-500">—</span>
  const color =
    score >= 80 ? 'text-red-400' :
    score >= 60 ? 'text-yellow-400' : 'text-gray-300'
  return <span className={`font-mono font-semibold ${color}`}>{score}</span>
}

export default async function QueuePage() {
  const data = await getQueue()

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Campaign Queue</h1>
        <span className="text-xs text-gray-500">Refreshes on load — dialer runs 9am & 1pm PT</span>
      </div>

      {!data ? (
        <div className="bg-red-900/30 border border-red-700 text-red-300 rounded-lg p-4">
          Failed to load queue. Is the backend running?
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
            <div className="bg-gray-800 rounded-lg p-5">
              <p className="text-sm text-gray-400 mb-1">Eligible for Dialing</p>
              <p className={`text-4xl font-bold ${data.eligible_count > 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.eligible_count}
              </p>
              <p className="text-xs text-gray-500 mt-1">callable + phones + ARV + score ≥ 50</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5">
              <p className="text-sm text-gray-400 mb-1">Callable Leads</p>
              <p className="text-4xl font-bold">{data.callable_count}</p>
              <p className="text-xs text-gray-500 mt-1">callable=true and opted_out=false</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5">
              <p className="text-sm text-gray-400 mb-1">Needs Enrichment</p>
              <p className={`text-4xl font-bold ${data.needs_enrich_count > 0 ? 'text-yellow-400' : 'text-gray-400'}`}>
                {data.needs_enrich_count}
              </p>
              <p className="text-xs text-gray-500 mt-1">callable=null, stage≠dead</p>
            </div>
          </div>

          {data.eligible_count === 0 && data.needs_enrich_count > 0 && (
            <div className="bg-yellow-900/30 border border-yellow-700 text-yellow-300 rounded-lg p-4 mb-6 text-sm">
              <strong>Eligible = 0.</strong> {data.needs_enrich_count} leads need enrichment to get phone numbers and callable status.
              Run BatchData enrichment via <code className="bg-yellow-900/50 px-1 rounded">POST /api/leads/{'{lead_id}'}/enrich</code>{' '}
              or manually activate test leads via <code className="bg-yellow-900/50 px-1 rounded">PATCH /api/leads/{'{lead_id}'}/activate?phone=2091234567</code>.
            </div>
          )}

          {data.top_10?.length > 0 && (
            <section>
              <h2 className="text-lg font-semibold mb-3 text-gray-200">
                Top {data.top_10.length} Eligible Leads
              </h2>
              <div className="bg-gray-800 rounded-lg overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-gray-700">
                      <th className="px-4 py-3">Address</th>
                      <th className="px-4 py-3 text-right">Score</th>
                      <th className="px-4 py-3 text-right">Composite</th>
                      <th className="px-4 py-3">Phones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_10.map((lead: any) => (
                      <tr key={lead.lead_id} className="border-b border-gray-700 hover:bg-gray-750">
                        <td className="px-4 py-3 max-w-xs truncate font-mono text-xs text-gray-300">
                          {lead.address || '—'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <ScoreBadge score={lead.score} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          <ScoreBadge score={lead.composite_score} />
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400">
                          {Array.isArray(lead.callable_phones)
                            ? lead.callable_phones.join(', ')
                            : lead.callable_phones || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.eligible_count === 0 && data.needs_enrich_count === 0 && (
            <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-500">
              No leads in system yet. <a href="/upload" className="text-blue-400 underline">Upload a CSV</a> to get started.
            </div>
          )}
        </>
      )}
    </main>
  )
}
