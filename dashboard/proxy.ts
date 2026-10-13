import { timingSafeEqual } from 'node:crypto'
import { NextRequest, NextResponse } from 'next/server'

function equal(left: string, right: string): boolean {
  const a = Buffer.from(left)
  const b = Buffer.from(right)
  return a.length === b.length && timingSafeEqual(a, b)
}

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith('/api/ingest/')) {
    const secret = process.env.KARPATHYS_WEBHOOK_SECRET || ''
    if (secret && equal(request.headers.get('x-karpathys-secret') || '', secret)) return NextResponse.next()
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  const user = process.env.DASHBOARD_USERNAME || ''
  const password = process.env.DASHBOARD_PASSWORD || ''
  const authorization = request.headers.get('authorization') || ''
  if (user && password && authorization.startsWith('Basic ')) {
    const decoded = Buffer.from(authorization.slice(6), 'base64').toString('utf8')
    if (equal(decoded, `${user}:${password}`)) return NextResponse.next()
  }
  return new NextResponse('Operator login required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="REI Operations", charset="UTF-8"' },
  })
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] }
