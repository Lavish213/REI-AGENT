'use client'

import { useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || ''

const TABS = ['Sophia', 'Campaign', 'Providers', 'Compliance', 'Integrations'] as const
type Tab = typeof TABS[number]

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="px-4 py-2 text-sm font-medium transition-colors border-b-2"
      style={{
        borderColor: active ? 'var(--teal)' : 'transparent',
        color: active ? 'var(--teal)' : 'var(--text-dim)',
      }}
    >
      {label}
    </button>
  )
}

function Card({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <div className="rounded-xl border p-5" style={{ borderColor: 'var(--border)', background: 'var(--bg-card)' }}>
      {title && <h3 className="text-xs font-semibold uppercase tracking-wide mb-4" style={{ color: 'var(--text-dim)' }}>{title}</h3>}
      {children}
    </div>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={`w-2 h-2 rounded-full inline-block ${ok ? 'bg-green-400' : 'bg-red-400'}`} />
}

function SophiaTab() {
  return (
    <div className="space-y-4">
      <Card title="Active Prompt">
        <p className="text-xs mb-3" style={{ color: 'var(--text-dim)' }}>
          Current <code style={{ color: 'var(--teal)' }}>sophia_core.md</code> — 700 token budget, 6 sections
        </p>
        <div className="rounded-lg p-3 text-xs font-mono leading-relaxed" style={{ background: 'var(--bg)', color: 'var(--text-dim)', maxHeight: 200, overflowY: 'auto' }}>
          Identity → Voice → Workflow → Objections → Guardrails → Tools
        </div>
        <div className="flex gap-3 mt-4">
          <a href={`${API}/api/health`} target="_blank" className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
            View Full Prompt
          </a>
          <button className="text-xs px-3 py-1.5 rounded font-medium" style={{ background: 'var(--teal)', color: 'var(--bg)' }}>
            Run Evals
          </button>
        </div>
      </Card>

      <Card title="Last Eval Scores">
        {[
          { label: 'Tone', score: 8.2 },
          { label: 'Goal Completion', score: 7.6 },
          { label: 'Objection Handling', score: 7.9 },
          { label: 'Appointment Booking', score: 6.8 },
        ].map(({ label, score }) => (
          <div key={label} className="flex items-center justify-between py-2 border-b last:border-0" style={{ borderColor: 'var(--border)' }}>
            <span className="text-sm" style={{ color: 'var(--text-dim)' }}>{label}</span>
            <span className="font-mono font-semibold text-sm" style={{ color: score >= 8 ? 'var(--green)' : score >= 7 ? 'var(--warm)' : 'var(--hot)' }}>
              {score}/10
            </span>
          </div>
        ))}
      </Card>
    </div>
  )
}

function CampaignTab() {
  return (
    <div className="space-y-4">
      <Card title="Call Settings">
        <div className="space-y-3">
          {[
            { label: 'Calling Hours', value: '8:00 AM – 9:00 PM PT' },
            { label: 'Max Concurrent Calls', value: '3' },
            { label: 'No-Answer Retry', value: '4 hours' },
            { label: 'Busy Retry', value: '30 minutes' },
            { label: 'Voicemail Retry', value: '24 hours' },
            { label: 'Max Attempts per Lead', value: '3 per day' },
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between text-sm py-1.5 border-b last:border-0" style={{ borderColor: 'var(--border)' }}>
              <span style={{ color: 'var(--text-dim)' }}>{label}</span>
              <span style={{ color: 'var(--text)' }}>{value}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Campaign Controls">
        <div className="flex gap-3">
          <button
            className="flex-1 py-2 text-sm rounded border transition-colors"
            style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}
            onClick={() => fetch(`${API}/api/campaigns/pause`, { method: 'POST' })}
          >
            Pause Campaign
          </button>
          <button
            className="flex-1 py-2 text-sm rounded border transition-colors"
            style={{ borderColor: 'var(--teal)', color: 'var(--teal)' }}
            onClick={() => fetch(`${API}/api/campaigns/resume`, { method: 'POST' })}
          >
            Resume Campaign
          </button>
          <button
            className="flex-1 py-2 text-sm rounded border transition-colors"
            style={{ borderColor: 'var(--gold)', color: 'var(--gold)' }}
            onClick={() => fetch(`${API}/api/campaigns/redial/default`, { method: 'POST' })}
          >
            Redial No-Answers
          </button>
        </div>
      </Card>
    </div>
  )
}

function ProvidersTab() {
  const providers = [
    { name: 'SignalWire', env: 'SIGNALWIRE_TOKEN', role: 'Telephony' },
    { name: 'Cartesia', env: 'CARTESIA_API_KEY', role: 'TTS — Sophia voice' },
    { name: 'Deepgram', env: 'DEEPGRAM_API_KEY', role: 'STT — nova-3' },
    { name: 'Anthropic', env: 'ANTHROPIC_API_KEY', role: 'LLM — Haiku 4.5' },
    { name: 'Supabase', env: 'SUPABASE_URL', role: 'Database' },
  ]

  return (
    <Card title="Provider Status">
      <div className="space-y-3">
        {providers.map(({ name, env, role }) => (
          <div key={name} className="flex items-center justify-between py-2 border-b last:border-0" style={{ borderColor: 'var(--border)' }}>
            <div>
              <p className="text-sm font-medium">{name}</p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{role}</p>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot ok={true} />
              <span className="text-xs" style={{ color: 'var(--text-dim)' }}>Connected</span>
            </div>
          </div>
        ))}
      </div>
      <button
        className="mt-4 text-xs px-3 py-1.5 rounded border"
        style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}
        onClick={() => window.open(`${API}/api/health`, '_blank')}
      >
        Run Health Check
      </button>
    </Card>
  )
}

function ComplianceTab() {
  return (
    <div className="space-y-4">
      <Card title="A2P 10DLC">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm">SMS Campaign Registration</p>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Required for bulk SMS delivery (95%+ rate)</p>
          </div>
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'var(--bg)', color: 'var(--warm)' }}>Pending</span>
        </div>
        <p className="text-xs mt-3" style={{ color: 'var(--text-dim)' }}>
          Register at: SignalWire Dashboard → Messaging → Campaign Registry
        </p>
      </Card>

      <Card title="California SB 1001 — AI Disclosure">
        <p className="text-xs leading-relaxed p-3 rounded" style={{ background: 'var(--bg)', color: 'var(--teal)', fontFamily: 'monospace' }}>
          "I'm Sophia — an automated assistant for San Joaquin House Buyers. Would you like to speak with someone directly?"
        </p>
        <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
          Fires automatically when seller sincerely asks if they're speaking with AI.
        </p>
      </Card>

      <Card title="TCPA Calling Hours">
        <div className="flex justify-between text-sm py-2">
          <span style={{ color: 'var(--text-dim)' }}>Allowed window</span>
          <span style={{ color: 'var(--text)' }}>8:00 AM – 9:00 PM PT</span>
        </div>
        <div className="flex justify-between text-sm py-2 border-t" style={{ borderColor: 'var(--border)' }}>
          <span style={{ color: 'var(--text-dim)' }}>DNC Check</span>
          <span style={{ color: 'var(--green)' }}>Active — checks before every call</span>
        </div>
      </Card>
    </div>
  )
}

function IntegrationsTab() {
  const integrations = [
    { name: 'Follow Up Boss', status: 'Pending', note: 'HOT disposition → FUB pipeline' },
    { name: 'Karpathys Event Bus', status: 'Pending', note: 'Call intel → Bob intelligence layer' },
    { name: 'SendGrid Inbound', status: 'Pending', note: 'Email reply → SMS alert to Angelo' },
    { name: 'Langfuse', status: 'Connected', note: 'Per-turn LLM tracing' },
  ]

  return (
    <Card title="Integration Status">
      <div className="space-y-3">
        {integrations.map(({ name, status, note }) => (
          <div key={name} className="flex items-center justify-between py-2 border-b last:border-0" style={{ borderColor: 'var(--border)' }}>
            <div>
              <p className="text-sm font-medium">{name}</p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{note}</p>
            </div>
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                color: status === 'Connected' ? 'var(--green)' : 'var(--warm)',
                background: 'var(--bg)',
              }}
            >
              {status}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('Sophia')

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold">Settings</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--text-dim)' }}>System configuration and status</p>
      </div>

      <div className="flex border-b mb-6" style={{ borderColor: 'var(--border)' }}>
        {TABS.map((t) => (
          <TabButton key={t} label={t} active={tab === t} onClick={() => setTab(t)} />
        ))}
      </div>

      {tab === 'Sophia' && <SophiaTab />}
      {tab === 'Campaign' && <CampaignTab />}
      {tab === 'Providers' && <ProvidersTab />}
      {tab === 'Compliance' && <ComplianceTab />}
      {tab === 'Integrations' && <IntegrationsTab />}
    </div>
  )
}
