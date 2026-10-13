'use client'

import { useEffect, useState } from 'react'
interface LiveEvent {
  id: string
  event_type: string
  payload: Record<string, unknown> | null
  created_at: string
  lead_id: string | null
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

const EVENT_COLORS: Record<string, string> = {
  call_started: 'text-green-400',
  call_ended: 'text-gray-400',
  transcript_completed: 'text-blue-400',
  disposition_set: 'text-yellow-400',
  followup_created: 'text-orange-400',
  appointment_scheduled: 'text-purple-400',
}

const EVENT_LABELS: Record<string, string> = {
  call_started: 'Call started',
  call_ended: 'Call ended',
  transcript_completed: 'Transcript ready',
  disposition_set: 'Disposition set',
  followup_created: 'Followup created',
  appointment_scheduled: 'Appointment booked',
}

export default function LiveActivity({ initialEvents = [] }: { initialEvents?: LiveEvent[] }) {
  const [events, setEvents] = useState<LiveEvent[]>(initialEvents)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let disposed = false
    async function refresh() {
      try {
        const response = await fetch('/api/events', { cache: 'no-store' })
        if (!response.ok) throw new Error('Activity unavailable')
        const data = await response.json()
        if (!disposed) { setEvents(data.events); setConnected(true) }
      } catch { if (!disposed) setConnected(false) }
    }
    void refresh()
    const timer = setInterval(refresh, 5000)
    return () => { disposed = true; clearInterval(timer) }
  }, [])

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
          Live Activity
        </h2>
        <span className="flex items-center gap-1.5 text-xs">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`} />
          <span className={connected ? 'text-green-400' : 'text-gray-600'}>
            {connected ? 'Updating every 5s' : 'Unavailable'}
          </span>
        </span>
      </div>

      <div className="bg-gray-800 rounded-lg overflow-hidden">
        {events.length === 0 ? (
          <div className="px-4 py-6 text-center text-gray-600 text-sm">
            Waiting for activity…
          </div>
        ) : (
          <ul className="divide-y divide-gray-700/50">
            {events.map((ev) => {
              const color = EVENT_COLORS[ev.event_type] ?? 'text-gray-400'
              const label = EVENT_LABELS[ev.event_type] ?? ev.event_type.replace(/_/g, ' ')
              const disposition = ev.payload?.disposition as string | undefined
              return (
                <li key={ev.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                  <span className="text-gray-600 text-xs font-mono w-20 shrink-0">
                    {formatTime(ev.created_at)}
                  </span>
                  <span className={`${color} shrink-0`}>{label}</span>
                  {disposition && (
                    <span className={`text-xs ${EVENT_COLORS['disposition_set']}`}>
                      {disposition}
                    </span>
                  )}
                  {ev.lead_id && (
                    <a
                      href={`/leads/${ev.lead_id}`}
                      className="ml-auto text-xs text-blue-400 hover:underline shrink-0"
                    >
                      Lead →
                    </a>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
