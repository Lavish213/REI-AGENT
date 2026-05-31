"use client"

import Link from 'next/link'

const API = process.env.NEXT_PUBLIC_API_URL || ''

async function fetchAPI(path: string) {
  try {
    const res = await fetch(`${API}/api${path}`, { cache: 'no-store' })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

function fmt$(cents: number | null) {
  if (!cents) return '$0'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function MetricCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className="rounded-xl p-4 border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
      <p className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--text-dim)' }}>{label}</p>
      <p className="text-3xl font-bold" style={{ color: accent || 'var(--text)' }}>{value}</p>
      {sub && <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{sub}</p>}
    </div>
  )
}

function DispositionBadge({ d }: { d: string }) {
  const map: Record<string, string> = {
    HOT: 'var(--hot)', WARM: 'var(--warm)', COLD: 'var(--cold)', DEAD: 'var(--dead)',
  }
  return (
    <span className="text-xs font-semibold px-2 py-0.5 rounded" style={{ color: map[d] || 'var(--text-dim)', background: 'var(--bg)' }}>
      {d}
    </span>
  )
}

export default async function CommandPage() {
  const [workflow, live, perf] = await Promise.all([
    fetchAPI('/analytics/workflow'),
    fetchAPI('/live/calls'),
    fetchAPI('/calls/performance/summary'),
  ])

  const w = workflow ?? {}
  const activeCalls: any[] = live?.active_calls ?? []
  const hotLeads: any[] = live?.hot_leads ?? []
  const overdueFollowups: any[] = live?.overdue_followups ?? []

  return (
    <div className="p-6 space-y-8">

      {/* Active calls */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-dim)' }}>
            Active Calls
          </h2>
          {activeCalls.length > 0 && (
            <span className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--green)' }}>
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              {activeCalls.length} live
            </span>
          )}
        </div>

        {activeCalls.length === 0 ? (
          <div className="rounded-xl border p-8 text-center text-sm" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            No active calls — Sophia is standing by
          </div>
        ) : (
          <div className="space-y-2">
            {activeCalls.map((call: any) => (
              <div key={call.call_sid} className="rounded-xl border px-4 py-3 flex items-center gap-4" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse shrink-0" />
                <span className="text-sm font-medium flex-1">{call.seller_name || call.address || call.call_sid}</span>
                <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{call.duration || '0:00'}</span>
                <span className="text-xs px-2 py-0.5 rounded" style={{ background: 'var(--bg)', color: 'var(--teal)' }}>{call.objective || 'DISCOVERY'}</span>
                {call.deal_heat > 7 && <span style={{ color: 'var(--hot)' }}>🔥</span>}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Today's summary */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--text-dim)' }}>Today</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <MetricCard label="Calls" value={w.calls_today ?? 0} />
          <MetricCard label="Connected" value={w.connected_today ?? 0} />
          <MetricCard label="Appointments" value={w.appointments_today ?? 0} accent="var(--green)" />
          <MetricCard label="Hot Leads" value={w.hot_leads ?? 0} accent="var(--hot)" />
          <MetricCard label="Conversion" value={w.conversion_rate_pct != null ? `${w.conversion_rate_pct}%` : '—'} accent="var(--teal)" />
          <MetricCard label="Avg QA" value={perf?.avg_score?.toFixed(1) ?? '—'} />
        </div>
      </section>

      {/* Priority queue + campaign side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Priority queue */}
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--text-dim)' }}>Priority Queue</h2>
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
            {hotLeads.length === 0 && overdueFollowups.length === 0 ? (
              <div className="p-6 text-sm text-center" style={{ color: 'var(--text-muted)' }}>Queue is clear</div>
            ) : (
              <div>
                {hotLeads.slice(0, 3).map((lead: any) => (
                  <div key={lead.id} className="flex items-center gap-3 px-4 py-3 border-b" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
                    <span style={{ color: 'var(--hot)' }}>🔥</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{lead.address}</p>
                      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{lead.owner_name || 'Unknown owner'}</p>
                    </div>
                    <DispositionBadge d="HOT" />
                    <Link href={`/leads/${lead.id}`} className="text-xs" style={{ color: 'var(--teal)' }}>View →</Link>
                  </div>
                ))}
                {overdueFollowups.slice(0, 3).map((f: any) => (
                  <div key={f.id} className="flex items-center gap-3 px-4 py-3 border-b last:border-0" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
                    <span style={{ color: 'var(--warm)' }}>⏰</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{f.address || 'Unknown address'}</p>
                      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Overdue followup</p>
                    </div>
                    <Link href={`/leads/${f.lead_id}`} className="text-xs" style={{ color: 'var(--teal)' }}>View →</Link>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Campaign status */}
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--text-dim)' }}>Campaign</h2>
          <div className="rounded-xl border p-5 space-y-4" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Outbound Campaign</p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Runs 9am + 1pm PT</p>
              </div>
              <span className="text-xs px-2 py-1 rounded font-medium" style={{ background: 'var(--bg)', color: 'var(--green)' }}>
                Running
              </span>
            </div>

            <div>
              <div className="flex justify-between text-xs mb-1.5" style={{ color: 'var(--text-dim)' }}>
                <span>Active slots</span>
                <span style={{ color: 'var(--text)' }}>{w.active_calls ?? 0} / 3</span>
              </div>
              <div className="h-1.5 rounded-full" style={{ background: 'var(--border)' }}>
                <div className="h-1.5 rounded-full" style={{ background: 'var(--teal)', width: `${Math.min(100, ((w.active_calls ?? 0) / 3) * 100)}%` }} />
              </div>
            </div>

            <div className="flex gap-2 pt-1">
              <button className="flex-1 text-xs py-2 rounded border transition-colors hover:opacity-80" style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}
                onClick={() => fetch(`${API}/api/campaigns/pause`, { method: 'POST' })}>
                Pause
              </button>
              <button className="flex-1 text-xs py-2 rounded border transition-colors hover:opacity-80" style={{ borderColor: 'var(--teal)', color: 'var(--teal)' }}
                onClick={() => fetch(`${API}/api/campaigns/resume`, { method: 'POST' })}>
                Resume
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Pipeline summary */}
      {w.stage_pipeline && (
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--text-dim)' }}>Pipeline</h2>
          <div className="grid grid-cols-4 md:grid-cols-7 gap-3">
            {Object.entries(w.stage_pipeline as Record<string, number>).map(([stage, count]) => (
              <Link key={stage} href="/leads" className="rounded-xl border p-3 text-center hover:opacity-80 transition-opacity" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
                <p className="text-2xl font-bold font-mono" style={{ color: count > 0 && stage !== 'dead' ? 'var(--text)' : 'var(--text-muted)' }}>{count}</p>
                <p className="text-xs mt-1 capitalize" style={{ color: 'var(--text-dim)' }}>{stage.replace(/_/g, ' ')}</p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
