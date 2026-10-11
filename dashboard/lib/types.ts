export interface OpsRow {
  id: string
  event_type: string
  created_at: string
  lead_id?: string
  payload?: { state?: string; priority?: string }
  properties?: { address?: string }
  leads?: { address?: string; workflow_state?: string }
  appointment_at?: string
  appt_day_before_sent?: boolean
  appt_morning_sent?: boolean
  appt_no_show_sent?: boolean
  workflow_state?: string
  motivation_level?: number
  timeline_urgency?: string
  next_best_action?: string
  followup_urgency?: string
  call_summary?: string
  hot_topics?: string[]
  priority?: string
  followup_type?: string
  created_by?: string
  notes?: string
  scheduled_at?: string
  state?: string
}

export interface LiveCall {
  lead_id?: string
  call_sid: string
  address?: string
  city?: string
  boss_mode?: boolean
  spanish?: boolean
  owner_first_name?: string
  lead_stage?: string
  started_at?: string
  metrics?: { objections_raised?: string[]; phase?: string; seller_energy?: string; turn_count?: number; disposition?: string; situation_label?: string; objective?: string; trust_score?: number; deal_heat?: number; emotional_state?: string; resistance_level?: string }
}
