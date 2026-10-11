import 'server-only'

export async function backendFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const base = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '')
  const token = process.env.OPERATOR_API_TOKEN
  if (!base || !token) throw new Error('Backend connection is not configured')
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${base}${path}`, { ...options, headers, cache: 'no-store' })
}
