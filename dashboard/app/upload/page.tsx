'use client'

import { useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || ''

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [minScore, setMinScore] = useState(50)
  const [createLeads, setCreateLeads] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')

  async function handleUpload() {
    if (!file) return
    setLoading(true)
    setError('')
    setResult(null)

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch(
        `${API}/api/properties/upload?min_score=${minScore}&create_leads=${createLeads}`,
        { method: 'POST', body: form }
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')
      setResult(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-900 text-white p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Upload Properties CSV</h1>

      <div className="bg-gray-800 rounded-lg p-6 space-y-5">
        <div>
          <label className="block text-sm text-gray-400 mb-2">CSV File (Propwire or compatible format)</label>
          <input
            type="file"
            accept=".csv"
            onChange={e => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-gray-300 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-gray-700 file:text-white hover:file:bg-gray-600 cursor-pointer"
          />
        </div>

        <div className="flex gap-6">
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-2">
              Min Score for Lead Creation
            </label>
            <input
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm"
            />
          </div>
          <div className="flex items-center gap-3 pt-6">
            <input
              id="create_leads"
              type="checkbox"
              checked={createLeads}
              onChange={e => setCreateLeads(e.target.checked)}
              className="w-4 h-4 accent-blue-500"
            />
            <label htmlFor="create_leads" className="text-sm text-gray-300">
              Auto-create leads for scored properties
            </label>
          </div>
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded font-medium transition-colors"
        >
          {loading ? 'Uploading…' : 'Upload & Process'}
        </button>
      </div>

      {error && (
        <div className="mt-4 bg-red-900/40 border border-red-700 text-red-300 rounded-lg p-4">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 bg-gray-800 rounded-lg p-6">
          <h2 className="font-semibold text-green-400 mb-4">Upload Complete</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              ['Rows parsed', result.parsed],
              ['Properties upserted', result.upserted],
              ['Scored (above min)', result.scored],
              ['Leads created', result.leads_created],
              ['Skipped (below min)', result.skipped_score],
              ['Errors', result.errors],
            ].map(([label, val]) => (
              <div key={label as string} className="flex justify-between">
                <span className="text-gray-400">{label}</span>
                <span className="font-mono font-semibold">{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-6 bg-gray-800 rounded-lg p-4 text-sm text-gray-400 space-y-1">
        <p className="font-medium text-gray-300">After upload:</p>
        <p>1. Check <a href="/queue" className="text-blue-400 underline">Campaign Queue</a> for eligible count.</p>
        <p>2. If eligible = 0 and leads need phones, use the Lead Activate button or run BatchData enrichment via the API.</p>
        <p>3. Outbound dialer runs automatically at 9am and 1pm PT.</p>
      </div>
    </main>
  )
}
