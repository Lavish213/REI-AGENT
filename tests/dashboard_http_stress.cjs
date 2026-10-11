const assert = require('node:assert/strict')
const http = require('node:http')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { once } = require('node:events')

async function main() {
  const failures = []
  let checks = 0
  let serverLog = ''
  const backend = http.createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const url = new URL(req.url, 'http://localhost')
    const status = Number(url.searchParams.get('status') || 200)
    if (url.searchParams.has("stall")) {
      setTimeout(() => res.end(), 20000).unref()
      return
    }
    res.statusCode = status
    if ([204, 304].includes(status)) return res.end()
    if (url.searchParams.has('close')) return req.socket.destroy()
    res.setHeader('content-type', 'application/json')
    res.end(JSON.stringify({ method: req.method, auth: req.headers.authorization, contentType: req.headers['content-type'], body: Buffer.concat(chunks).toString('base64'), query: url.searchParams.get('query') }))
  })
  backend.listen(0, '127.0.0.1')
  await once(backend, 'listening')
  const reserve = http.createServer()
  reserve.listen(0, '127.0.0.1')
  await once(reserve, 'listening')
  const port = reserve.address().port
  await new Promise(resolve => reserve.close(resolve))
  const dashboard = path.resolve(__dirname, '../dashboard')
  const child = spawn(process.execPath, [path.join(dashboard, 'node_modules/next/dist/bin/next'), 'start', '-p', String(port), '-H', '127.0.0.1'], {
    cwd: dashboard,
    env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${backend.address().port}`, OPERATOR_API_TOKEN: 'operator-test', DASHBOARD_USERNAME: 'tester', DASHBOARD_PASSWORD: 'password-test', NEXT_PUBLIC_SUPABASE_URL: 'https://example.supabase.co', SUPABASE_SERVICE_KEY: 'test-key', KARPATHYS_WEBHOOK_SECRET: 'ingest-test' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout.on('data', data => { serverLog += data })
  child.stderr.on('data', data => { serverLog += data })
  const base = `http://127.0.0.1:${port}`
  const auth = { Authorization: 'Basic ' + Buffer.from('tester:password-test').toString('base64') }
  async function check(name, run) {
    checks++
    try { await run() } catch (error) { failures.push({ name, error: error.message }) }
  }
  try {
    for (let i = 0; i < 100; i++) {
      try { await fetch(base, { signal: AbortSignal.timeout(300) }); break } catch {
        if (child.exitCode !== null) throw new Error('Dashboard exited: ' + serverLog.slice(-2000))
        if (i === 99) throw new Error('Dashboard did not start')
        await new Promise(resolve => setTimeout(resolve, 100))
      }
    }
    for (const route of ['/', '/settings', '/api/events', '/api/backend/api/health']) {
      await check('unauthenticated ' + route, async () => assert.equal((await fetch(base + route)).status, 401))
    }
    await check('wrong password', async () => assert.equal((await fetch(base + '/settings', { headers: { Authorization: 'Basic ' + Buffer.from('tester:wrong').toString('base64') } })).status, 401))
    await check('invalid proxy path', async () => assert.equal((await fetch(base + '/api/backend/health', { headers: auth })).status, 400))
    await check('ingest secret required', async () => assert.equal((await fetch(base + '/api/ingest/call', { method: 'POST', body: '{}', headers: { ...auth, 'content-type': 'application/json' } })).status, 401))
    for (const status of [200, 201, 202, 204, 205, 304, 400, 401, 403, 404, 409, 422, 429, 500, 503]) {
      await check('backend status ' + status, async () => assert.equal((await fetch(base + '/api/backend/api/test?status=' + status, { headers: auth })).status, status))
    }
    for (const method of ['GET', 'POST', 'PATCH', 'DELETE']) {
      await check('method/body ' + method, async () => {
        const body = Buffer.from('testing 🌵 binary \x00 body')
        const response = await fetch(base + '/api/backend/api/test?query=exact%20value', { method, headers: { ...auth, 'content-type': 'application/octet-stream' }, body: method === 'GET' ? undefined : body })
        const result = await response.json()
        assert.equal(result.method, method)
        assert.equal(result.auth, 'Bearer operator-test')
        assert.equal(result.query, 'exact value')
        if (method !== 'GET') assert.equal(result.body, body.toString('base64'))
      })
    }
    await check('multipart upload byte preservation', async () => {
      const form = new FormData()
      form.set('file', new Blob(['address,city\n100 Test Ave,Stockton\n']), 'test.csv')
      const response = await fetch(base + '/api/backend/api/test', { method: 'POST', headers: auth, body: form })
      const result = await response.json()
      assert.match(result.contentType, /^multipart\/form-data; boundary=/)
      const payload = Buffer.from(result.body, 'base64').toString()
      assert.match(payload, /filename="test.csv"/)
      assert.match(payload, /100 Test Ave,Stockton/)
    })
    await check('provider socket failure becomes 502', async () => assert.equal((await fetch(base + '/api/backend/api/test?close=1', { headers: auth })).status, 502))
    await check('stalled backend aborts within deadline', async () => {
      const start = Date.now()
      const response = await fetch(base + '/api/backend/api/test?stall=1', { headers: auth, signal: AbortSignal.timeout(20000) })
      assert.equal(response.status, 502)
      assert(Date.now() - start < 18000)
    })
    await check('100 concurrent proxy requests', async () => {
      const responses = await Promise.all(Array.from({ length: 100 }, () => fetch(base + '/api/backend/api/test', { headers: auth })))
      assert(responses.every(response => response.status === 200))
      for (const response of responses) assert.equal((await response.json()).auth, 'Bearer operator-test')
    })
    process.stdout.write(JSON.stringify({ checks, passed: checks - failures.length, failures }, null, 2) + '\n')
    if (failures.length) process.exitCode = 1
  } finally {
    child.kill('SIGTERM')
    await once(child, 'exit').catch(() => {})
    backend.closeAllConnections()
    await new Promise(resolve => backend.close(resolve))
  }
}

main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1 })
