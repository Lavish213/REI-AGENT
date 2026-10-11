import { supabase } from '@/lib/supabase'
import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { error } = await supabase.from('call_events').insert({
      call_id: body.call_id || null,
      lead_id: body.lead_id || null,
      event_type: 'transcript_completed',
      payload: body,
    })
    if (error) throw error
    return NextResponse.json({ ok: true })
  } catch {
    return NextResponse.json({ ok: false }, { status: 500 })
  }
}
