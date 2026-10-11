import { NextRequest, NextResponse } from 'next/server'
import { backendFetch } from '@/lib/backend'

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params
  if (path[0] !== 'api') return NextResponse.json({ error: 'Invalid API path' }, { status: 400 })
  try {
    const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer()
    const response = await backendFetch(`/${path.map(encodeURIComponent).join('/')}${request.nextUrl.search}`, {
      method: request.method,
      body,
      headers: { 'Content-Type': request.headers.get('content-type') || 'application/json' },
    })
    const responseBody = [204, 205, 304].includes(response.status) ? null : await response.arrayBuffer()
    return new NextResponse(responseBody, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    })
  } catch {
    return NextResponse.json({ error: 'Backend is unavailable' }, { status: 502 })
  }
}

export const GET = forward
export const POST = forward
export const PATCH = forward
export const DELETE = forward
