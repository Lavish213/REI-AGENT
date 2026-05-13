import { supabase } from '@/lib/supabase'
import { notFound } from 'next/navigation'

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function formatCurrency(cents: number | null) {
  if (cents == null) return null
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function DispositionBadge({ disposition }: { disposition: string | null }) {
  if (!disposition) return <span className="text-gray-500">—</span>
  const colors: Record<string, string> = {
    HOT: 'bg-red-600 text-red-100',
    WARM: 'bg-yellow-600 text-yellow-100',
    COLD: 'bg-blue-700 text-blue-100',
    DEAD: 'bg-gray-600 text-gray-300',
  }
  const cls = colors[disposition] ?? 'bg-gray-600 text-gray-300'
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>{disposition}</span>
}

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  if (value == null) return null
  const pct = Math.round((value / 10) * 100)
  const color = value >= 8 ? 'bg-green-500' : value >= 6 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-400 text-xs w-32 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-700 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-300 text-xs font-mono w-8 text-right">{value.toFixed(1)}</span>
    </div>
  )
}

function MotivationMeter({ level }: { level: number | null }) {
  if (level == null) return <span className="text-gray-500 text-sm">Unknown</span>
  const color = level >= 8 ? 'text-red-400' : level >= 6 ? 'text-yellow-400' : 'text-gray-300'
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: 10 }, (_, i) => (
        <div
          key={i}
          className={`h-3 w-2 rounded-sm ${i < level ? (level >= 8 ? 'bg-red-500' : level >= 6 ? 'bg-yellow-500' : 'bg-gray-400') : 'bg-gray-700'}`}
        />
      ))}
      <span className={`ml-1 text-sm font-semibold ${color}`}>{level}/10</span>
    </div>
  )
}

export default async function CallDetailPage({ params }: { params: { id: string } }) {
  const { id } = params

  const [callResp, chunksResp, eventsResp] = await Promise.all([
    supabase
      .from('calls')
      .select(`
        id, created_at, signalwire_call_id, direction, call_disposition,
        call_summary, seller_name, seller_motivation, motivation_confidence,
        asking_price, occupancy, property_condition, distress_indicators,
        objections, appointment_interest, next_step, followup_priority,
        lead_score, extraction_confidence, timeline, sentiment_arc,
        phase_reached, score_overall, score_qualification, score_offer_quality,
        score_objection_handling, score_appointment_booking, score_tone,
        score_goal_completion, summary,
        leads(id, address, distress_score, motivation_level, timeline_urgency, is_hot_lead, stage)
      `)
      .eq('id', id)
      .single(),

    supabase
      .from('transcript_chunks')
      .select('id, speaker, text, chunk_type, sequence_order, confidence')
      .eq('call_id', id)
      .order('sequence_order'),

    supabase
      .from('call_events')
      .select('event_type, payload, created_at')
      .eq('call_id', id)
      .order('created_at'),
  ])

  if (!callResp.data) notFound()

  const call = callResp.data as any
  const chunks = chunksResp.data ?? []
  const events = eventsResp.data ?? []
  const lead = call.leads as any

  const disposition = call.call_disposition
  const hasSummary = !!call.call_summary
  const hasChunks = chunks.length > 0

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <a href="/calls" className="text-blue-400 text-sm hover:underline mb-2 inline-block">← Back to calls</a>
          <h1 className="text-2xl font-bold">{lead?.address ?? 'Unknown Address'}</h1>
          <p className="text-gray-400 text-sm mt-1">{formatDate(call.created_at)} · {call.direction ?? 'inbound'}</p>
        </div>
        <div className="flex items-center gap-3">
          <DispositionBadge disposition={disposition} />
          {call.is_hot_lead || lead?.is_hot_lead ? (
            <span className="bg-red-900/60 text-red-300 text-xs px-2 py-1 rounded font-semibold">HOT LEAD</span>
          ) : null}
          {call.score_overall != null && (
            <div className="text-center">
              <div className={`text-2xl font-bold font-mono ${call.score_overall >= 8 ? 'text-green-400' : call.score_overall >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>
                {call.score_overall.toFixed(1)}
              </div>
              <div className="text-gray-500 text-xs">QA Score</div>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column: transcript + events */}
        <div className="lg:col-span-2 space-y-6">

          {/* Transcript */}
          <section className="bg-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Transcript {hasChunks ? `(${chunks.length} turns)` : ''}
            </h2>
            {hasChunks ? (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {chunks.map((chunk: any) => (
                  <div
                    key={chunk.id}
                    className={`flex gap-2 ${chunk.speaker === 'SOPHIA' ? 'flex-row-reverse' : ''}`}
                  >
                    <div className={`text-xs font-semibold shrink-0 pt-0.5 ${chunk.speaker === 'SOPHIA' ? 'text-blue-400' : 'text-green-400'}`}>
                      {chunk.speaker}
                    </div>
                    <div className={`text-sm rounded-lg px-3 py-2 max-w-sm leading-relaxed ${
                      chunk.speaker === 'SOPHIA'
                        ? 'bg-blue-900/40 text-gray-200 ml-auto'
                        : 'bg-gray-700 text-gray-200'
                    }`}>
                      {chunk.text}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-500 text-sm italic">No structured transcript available</p>
            )}
          </section>

          {/* QA Scores */}
          {call.score_overall != null && (
            <section className="bg-gray-800 rounded-lg p-5">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">QA Scores</h2>
              <div className="space-y-2">
                <ScoreBar label="Qualification" value={call.score_qualification} />
                <ScoreBar label="Offer Quality" value={call.score_offer_quality} />
                <ScoreBar label="Objection Handling" value={call.score_objection_handling} />
                <ScoreBar label="Appointment Booking" value={call.score_appointment_booking} />
                <ScoreBar label="Tone" value={call.score_tone} />
                <ScoreBar label="Goal Completion" value={call.score_goal_completion} />
              </div>
              {call.sentiment_arc && (
                <p className="text-xs text-gray-400 mt-3">
                  <span className="text-gray-500">Sentiment arc:</span> {call.sentiment_arc}
                </p>
              )}
              {call.phase_reached && (
                <p className="text-xs text-gray-400">
                  <span className="text-gray-500">Phase reached:</span> {call.phase_reached}
                </p>
              )}
              {call.summary && (
                <p className="text-sm text-gray-300 mt-3 border-t border-gray-700 pt-3 italic">{call.summary}</p>
              )}
            </section>
          )}

          {/* Event timeline */}
          {events.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-5">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">Event Timeline</h2>
              <div className="space-y-1">
                {events.map((ev: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 text-xs">
                    <span className="text-gray-600 w-20 shrink-0">{new Date(ev.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span>
                    <span className="font-mono text-blue-300">{ev.event_type}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* Right column: intelligence cards */}
        <div className="space-y-4">

          {/* Call Summary */}
          {hasSummary && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Call Summary</h2>
              <p className="text-sm text-gray-200 leading-relaxed">{call.call_summary}</p>
            </section>
          )}

          {/* Seller Insights */}
          <section className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Seller Insights</h2>
            <div className="space-y-3">
              <div>
                <p className="text-gray-500 text-xs mb-1">Motivation</p>
                <MotivationMeter level={call.motivation_level ?? lead?.motivation_level} />
                {call.seller_motivation && (
                  <p className="text-gray-400 text-xs mt-1 italic">{call.seller_motivation}</p>
                )}
              </div>
              {(call.timeline_urgency || lead?.timeline_urgency) && (
                <div>
                  <p className="text-gray-500 text-xs">Timeline</p>
                  <p className="text-gray-200 text-sm capitalize">{call.timeline_urgency ?? lead?.timeline_urgency}</p>
                  {call.timeline && <p className="text-gray-400 text-xs italic">{call.timeline}</p>}
                </div>
              )}
              {call.seller_name && (
                <div>
                  <p className="text-gray-500 text-xs">Seller Name</p>
                  <p className="text-gray-200 text-sm">{call.seller_name}</p>
                </div>
              )}
              {call.asking_price != null && (
                <div>
                  <p className="text-gray-500 text-xs">Asking Price</p>
                  <p className="text-yellow-300 text-sm font-mono font-semibold">{formatCurrency(call.asking_price)}</p>
                </div>
              )}
              {call.appointment_interest != null && (
                <div>
                  <p className="text-gray-500 text-xs">Appointment Interest</p>
                  <p className={`text-sm font-semibold ${call.appointment_interest ? 'text-green-400' : 'text-red-400'}`}>
                    {call.appointment_interest ? 'Yes' : 'No'}
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* Property Insights */}
          {(call.property_condition || call.occupancy || call.property_address_mentioned) && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Property Insights</h2>
              <div className="space-y-2 text-sm">
                {call.property_condition && call.property_condition !== 'unknown' && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Condition</span>
                    <span className="text-gray-200 capitalize">{call.property_condition}</span>
                  </div>
                )}
                {call.occupancy && call.occupancy !== 'unknown' && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Occupancy</span>
                    <span className="text-gray-200">{call.occupancy.replace(/_/g, ' ')}</span>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Distress Indicators */}
          {Array.isArray(call.distress_indicators) && call.distress_indicators.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Distress Signals</h2>
              <div className="flex flex-wrap gap-1">
                {call.distress_indicators.map((d: string, i: number) => (
                  <span key={i} className="bg-red-900/40 text-red-300 text-xs px-2 py-0.5 rounded">{d}</span>
                ))}
              </div>
            </section>
          )}

          {/* Objections */}
          {Array.isArray(call.objections) && call.objections.length > 0 && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Objections</h2>
              <ul className="space-y-1">
                {call.objections.map((o: string, i: number) => (
                  <li key={i} className="text-xs text-gray-300">• {o}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Next Step */}
          {(call.next_step || call.followup_priority) && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Next Step</h2>
              {call.followup_priority && (
                <span className={`text-xs px-2 py-0.5 rounded mb-2 inline-block ${
                  call.followup_priority === 'high' ? 'bg-red-900/50 text-red-300' :
                  call.followup_priority === 'medium' ? 'bg-yellow-900/50 text-yellow-300' :
                  'bg-gray-700 text-gray-400'
                }`}>{call.followup_priority} priority</span>
              )}
              {call.next_step && <p className="text-sm text-gray-200">{call.next_step}</p>}
            </section>
          )}

          {/* Lead Score + Extraction Confidence */}
          {(call.lead_score != null || call.extraction_confidence != null) && (
            <section className="bg-gray-800 rounded-lg p-4">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Intelligence Quality</h2>
              <div className="space-y-1 text-xs">
                {call.lead_score != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Lead Score</span>
                    <span className="font-mono font-semibold text-gray-200">{call.lead_score.toFixed(1)}/10</span>
                  </div>
                )}
                {call.extraction_confidence != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Extraction Confidence</span>
                    <span className="font-mono text-gray-400">{Math.round(call.extraction_confidence * 100)}%</span>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </main>
  )
}
