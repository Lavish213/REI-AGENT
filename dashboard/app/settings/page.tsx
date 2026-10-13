'use client'

import { useEffect, useState } from 'react'

type Result = Record<string, unknown>

export default function SettingsPage() {
  const [health, setHealth] = useState<Result | null>(null)
  const [campaign, setCampaign] = useState<Result | null>(null)
  const [message, setMessage] = useState('Loading connection status…')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    const [h, c] = await Promise.all([
      fetch('/api/backend/api/health', { cache: 'no-store' }),
      fetch('/api/backend/api/campaigns/status', { cache: 'no-store' }),
    ])
    if (!h.ok || !c.ok) throw new Error('Backend connection is unavailable')
    setHealth(await h.json())
    setCampaign(await c.json())
  }

  useEffect(() => {
    const timer = setTimeout(() => { refresh().then(() => setMessage('Status loaded.')).catch(error => setMessage(error.message)) }, 0)
    return () => clearTimeout(timer)
  }, [])

  async function action(path: string) {
    setBusy(true)
    try {
      const response = await fetch(`/api/backend/api/${path}`, { method: 'POST' })
      const result = await response.json()
      if (!response.ok || result.error || result.success === false) throw new Error(result.detail || result.error || 'Action failed')
      setMessage('Action accepted. Refreshing status…')
      await refresh()
      setMessage('Status updated.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Action failed')
    } finally { setBusy(false) }
  }

  return <div className="p-6 space-y-6">
    <h1 className="text-2xl font-semibold">Operations settings</h1>
    <p role="status">{message}</p>
    <section className="rounded-xl border p-5 space-y-3">
      <h2 className="font-semibold">Campaign</h2>
      <div className="flex gap-3">
        <button disabled={busy} onClick={() => action('campaigns/pause')} className="border rounded px-4 py-2">Pause calls</button>
        <button disabled={busy} onClick={() => action('campaigns/resume')} className="border rounded px-4 py-2">Resume calls</button>
      </div>
      <pre className="overflow-auto text-xs">{campaign ? JSON.stringify(campaign, null, 2) : 'Status unavailable'}</pre>
    </section>
    <section className="rounded-xl border p-5 space-y-3">
      <h2 className="font-semibold">Provider status</h2>
      <pre className="overflow-auto text-xs">{health ? JSON.stringify(health, null, 2) : 'Status unavailable'}</pre>
    </section>
    <section className="rounded-xl border p-5 space-y-3">
      <h2 className="font-semibold">Voice evaluation</h2>
      <p className="text-sm">Conversation scenarios check text behavior. Recorded phone calls are required to assess audio, latency, and interruptions.</p>
      <button disabled={busy} onClick={() => action('evals/run')} className="border rounded px-4 py-2">Run conversation scenarios</button>
      <a className="block text-sm underline" href="/api/backend/api/evals/history" download="voice-evaluations.json">Download saved evaluations</a>
    </section>
  </div>
}
