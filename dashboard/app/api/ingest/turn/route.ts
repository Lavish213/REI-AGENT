import { getSupabase } from '@/lib/supabase'
import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { error } = await getSupabase().from('bob_feedback_events').insert({
      lead_id: body.lead_id || null,
      call_sid: body.call_sid || null,
      event_type: 'turn_signal',
      payload: body,
      source: 'sophia',
    })
    if (error) throw error
    return NextResponse.json({ ok: true })
  } catch {
    return NextResponse.json({ ok: false }, { status: 500 })
  }
}
