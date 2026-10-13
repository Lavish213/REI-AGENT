import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export async function GET() {
  const { data, error } = await getSupabase().from('call_events').select('id,event_type,payload,created_at,lead_id').order('created_at', { ascending: false }).limit(20)
  if (error) return NextResponse.json({ error: 'Activity is unavailable' }, { status: 502 })
  return NextResponse.json({ events: data || [] })
}
