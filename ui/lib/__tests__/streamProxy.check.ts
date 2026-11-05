/**
 * SECREL-01 / C2-security-01: the optional Next :3000 server's six stream proxies (ui/app/api/**\/route.ts) must hand
 * ui-api the browser context Next's own `/api` rewrite forwards (Origin, Sec-Fetch-Site, X-Forwarded-Host = the
 * browser's Host), so shared/http_guard.py judges a request through them like any other. Plain node 25 (type
 * stripping, no deps), also type-checked by `cd ui && npx tsc --noEmit`:
 *
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/streamProxy.check.ts
 *
 * End to end, with no live service touched:
 *  1. the REAL route modules run against a fake upstream on an ephemeral loopback port (the headers are captured
 *     ON THE WIRE, i.e. after Node's fetch applied its own rules);
 *  2. the captured headers go through the REAL guard (shared/http_guard.py `evaluate`, default policy) in the
 *     stack's Python (SURYADHANA_PY, default /Users/sudheer/Desktop/jupyter_env/bin/python, else python3);
 *  3. negative control: the pre-fix mapping (content-type / accept only) gets the same cross-site POST ADMITTED by
 *     the guard, so this check fails on the old route handlers.
 * Exits non-zero on any failing check.
 */
import * as nodeModule from 'node:module'
import * as http from 'node:http'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { spawnSync } from 'node:child_process'
import type { AddressInfo } from 'node:net'

const UI_ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..')
const REPO_ROOT = path.resolve(UI_ROOT, '..')

;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    if (spec.startsWith('@/')) return next(new URL(`file://${UI_ROOT}/${spec.slice(2)}.ts`).href, ctx)
    try {
      return next(spec, ctx)
    } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) {
    passed++
    return
  }
  failed++
  console.error(`FAIL ${name}${extra === undefined ? '' : ` — ${JSON.stringify(extra)}`}`)
}

type StreamProxyMod = typeof import('../streamProxy')
type Wire = Record<string, string[]>

// ── fake upstream: records every request's headers exactly as received ─────────────────────────────────────────
const seen: Array<{ method: string; url: string; headers: Wire; body: string }> = []
let upstreamStatus = 200
const server = http.createServer((req, res) => {
  let body = ''
  req.on('data', c => { body += c })
  req.on('end', () => {
    const headers: Wire = {}
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      const k = req.rawHeaders[i].toLowerCase()
      ;(headers[k] ??= []).push(req.rawHeaders[i + 1])
    }
    seen.push({ method: req.method ?? '', url: req.url ?? '', headers, body })
    res.writeHead(upstreamStatus, { 'content-type': 'text/plain' })
    res.end('ok')
  })
})
await new Promise<void>(r => server.listen(0, '127.0.0.1', r))
const port = (server.address() as AddressInfo).port
process.env.NEXT_PUBLIC_API_BASE = `http://127.0.0.1:${port}`

// ── the six handlers (imported AFTER the env is set: each reads API_BACKEND at module load) ─────────────────────
type Handler = (req: unknown, ctx?: unknown) => Promise<Response>
const ROUTES: Array<{ file: string; method: 'GET' | 'POST'; path: string; upstream: string; job?: boolean }> = [
  { file: 'app/api/ml/train/stream/route.ts', method: 'POST', path: '/api/ml/train/stream', upstream: '/api/ml/train/stream' },
  { file: 'app/api/analytics/backtest/stream/route.ts', method: 'POST', path: '/api/analytics/backtest/stream', upstream: '/api/analytics/backtest/stream' },
  { file: 'app/api/analytics/wfo-backtest/stream/route.ts', method: 'POST', path: '/api/analytics/wfo-backtest/stream', upstream: '/api/analytics/wfo-backtest/stream' },
  { file: 'app/api/telemetry/logs/stream/route.ts', method: 'GET', path: '/api/telemetry/logs/stream?tail=5', upstream: '/api/telemetry/logs/stream?tail=5' },
  { file: 'app/api/pipeline/ml-stream/[job_id]/route.ts', method: 'GET', path: '/api/pipeline/ml-stream/j1', upstream: '/api/pipeline/ml-stream/j1', job: true },
  { file: 'app/api/pipeline/rl-stream/[job_id]/route.ts', method: 'GET', path: '/api/pipeline/rl-stream/j1', upstream: '/api/pipeline/rl-stream/j1', job: true },
]
check('six route handlers found', ROUTES.every(r => fs.existsSync(path.join(UI_ROOT, r.file))))
const onDisk = fs.readdirSync(path.join(UI_ROOT, 'app/api'), { recursive: true }).map(String).filter(f => f.endsWith('route.ts')).length
check('no route handler outside this list (a new one must be covered here)', onDisk === ROUTES.length, onDisk)

/** A NextRequest as the handlers use it: Fetch Request + nextUrl. */
function browserRequest(method: 'GET' | 'POST', urlPath: string, headers: Record<string, string>): unknown {
  const host = headers.host ?? 'localhost:3000'
  const url = `http://${host}${urlPath}`
  const req = new Request(url, { method, headers, body: method === 'POST' ? '{"mode":"production"}' : undefined })
  return Object.assign(req, { nextUrl: new URL(url) })
}

async function drive(route: (typeof ROUTES)[number], headers: Record<string, string>): Promise<{ status: number; wire: Wire }> {
  const mod = (await import(new URL(`file://${UI_ROOT}/${route.file}`).href)) as Record<string, Handler>
  const fn = mod[route.method]
  const before = seen.length
  const res = await fn(browserRequest(route.method, route.path, headers), route.job ? { params: Promise.resolve({ job_id: 'j1' }) } : undefined)
  await res.text()
  const got = seen.slice(before)
  if (got.length !== 1) throw new Error(`${route.file}: ${got.length} upstream requests`)
  check(`${route.file}: upstream path kept`, got[0].url === route.upstream, got[0].url)
  check(`${route.file}: upstream method kept`, got[0].method === route.method, got[0].method)
  return { status: res.status, wire: got[0].headers }
}

// ── the real guard, in the stack's Python ───────────────────────────────────────────────────────────────────────
interface Verdict { allowed: boolean; status: number; reason: string }
function guard(cases: Array<{ method: string; headers: Wire }>): Verdict[] | null {
  const py = process.env.SURYADHANA_PY || '/Users/sudheer/Desktop/jupyter_env/bin/python'
  // shared/http_guard.py is stdlib-only; it is loaded by file path so the package __init__ (pydantic settings) is not
  // needed: the check runs with any python3 (the CI ui job has no Python dependencies)
  const code = [
    'import importlib.util, json, sys',
    `spec = importlib.util.spec_from_file_location('sd_http_guard', ${JSON.stringify(path.join(REPO_ROOT, 'shared', 'http_guard.py'))})`,
    'g = importlib.util.module_from_spec(spec); sys.modules[spec.name] = g; spec.loader.exec_module(g)',
    'GuardPolicy, evaluate = g.GuardPolicy, g.evaluate',
    'policy = GuardPolicy.from_env({})',
    'out = []',
    'for c in json.load(sys.stdin):',
    "    d = evaluate(policy, scope_type='http', method=c['method'], headers=c['headers'], client=('127.0.0.1', 50000))",
    "    out.append({'allowed': d.allowed, 'status': d.status, 'reason': d.reason})",
    'print(json.dumps(out))',
  ].join('\n')
  for (const exe of [py, 'python3']) {
    const r = spawnSync(exe, ['-c', code], { input: JSON.stringify(cases), encoding: 'utf8' })
    if (r.status === 0) return JSON.parse(r.stdout) as Verdict[]
  }
  return null
}

const S = (await import(new URL(`file://${UI_ROOT}/lib/streamProxy.ts`).href)) as StreamProxyMod

// pure mapping
const h = (o: Record<string, string>) => new Headers(o)
const m = S.streamProxyHeaders(h({ host: 'localhost:3000', origin: 'https://evil.example', 'sec-fetch-site': 'cross-site', cookie: 'a=b',
  'x-forwarded-host': 'spoof.example', authorization: 'Bearer x' }), { 'content-type': 'application/json' })
check('mapping: X-Forwarded-Host = incoming Host (overrides an incoming one, like the rewrite)', m['x-forwarded-host'] === 'localhost:3000', m)
check('mapping: Origin and Sec-Fetch-Site forwarded', m.origin === 'https://evil.example' && m['sec-fetch-site'] === 'cross-site', m)
check('mapping: base headers kept', m['content-type'] === 'application/json', m)
check('mapping: no cookie / authorization leaves the browser request', !('cookie' in m) && !('authorization' in m), m)
const local = S.streamProxyHeaders(h({ host: '127.0.0.1:3000' }), { accept: 'text/event-stream' })
check('mapping: a no-Origin local client stays no-Origin', !('origin' in local) && !('sec-fetch-site' in local) && local['x-forwarded-host'] === '127.0.0.1:3000', local)

// ── scenarios through every handler ─────────────────────────────────────────────────────────────────────────────
const CROSS_SITE = { host: 'localhost:3000', origin: 'https://evil.example', 'sec-fetch-site': 'cross-site', 'content-type': 'text/plain' }
const SAME_ORIGIN = { host: 'localhost:3000', origin: 'http://localhost:3000', 'sec-fetch-site': 'same-origin', 'content-type': 'application/json' }
const REBIND = { host: 'rebind.attacker.example:3000', 'sec-fetch-site': 'same-origin' }
const SCRIPT = { host: '127.0.0.1:3000' }
const REMOTE = { ...SAME_ORIGIN, 'x-forwarded-for': '100.64.0.7' }
const cases: Array<{ name: string; route: (typeof ROUTES)[number]; method: string; headers: Wire; want: (v: Verdict) => boolean; wantText: string }> = []
for (const route of ROUTES) {
  if (route.method === 'POST') {
    const x = await drive(route, CROSS_SITE)
    check(`${route.file}: wire carries the browser's Origin + Sec-Fetch-Site`,
      x.wire.origin?.[0] === 'https://evil.example' && x.wire['sec-fetch-site']?.[0] === 'cross-site', x.wire)
    check(`${route.file}: wire X-Forwarded-Host = the browser's Host`, x.wire['x-forwarded-host']?.[0] === 'localhost:3000', x.wire)
    cases.push({ name: `${route.file}: cross-site text/plain POST`, route, method: 'POST', headers: x.wire, want: v => !v.allowed && v.status === 403, wantText: '403' })
    cases.push({ name: `${route.file}: the :3000 terminal's own POST`, route, method: 'POST', headers: (await drive(route, SAME_ORIGIN)).wire, want: v => v.allowed, wantText: 'allowed' })
    cases.push({ name: `${route.file}: local script POST (no Origin)`, route, method: 'POST', headers: (await drive(route, SCRIPT)).wire, want: v => v.allowed, wantText: 'allowed' })
    cases.push({ name: `${route.file}: remote client behind a proxy`, route, method: 'POST', headers: (await drive(route, REMOTE)).wire,
      want: v => !v.allowed && v.reason === 'remote_write', wantText: '403 remote_write' })
  } else {
    const x = await drive(route, REBIND)
    check(`${route.file}: wire X-Forwarded-Host = the rebinding Host`, x.wire['x-forwarded-host']?.[0] === 'rebind.attacker.example:3000', x.wire)
    cases.push({ name: `${route.file}: DNS-rebinding GET`, route, method: 'GET', headers: x.wire, want: v => !v.allowed && v.status === 400, wantText: '400' })
    cases.push({ name: `${route.file}: the :3000 terminal's own GET`, route, method: 'GET', headers: (await drive(route, { host: 'localhost:3000' })).wire,
      want: v => v.allowed, wantText: 'allowed' })
  }
}
// the upstream status (the guard's 403 / 400) reaches the browser unchanged
upstreamStatus = 403
check('the guard status passes through the handler', (await drive(ROUTES[0], CROSS_SITE)).status === 403)
upstreamStatus = 200

// negative control: the pre-fix handlers sent only their own content-type / accept
const before = seen.length
await (await fetch(`http://127.0.0.1:${port}/api/ml/train/stream`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })).text()
const oldWire = seen[before].headers
await (await fetch(`http://127.0.0.1:${port}/api/telemetry/logs/stream`, { headers: { accept: 'text/event-stream' } })).text()
const oldGetWire = seen[before + 1].headers

const verdicts = guard([...cases.map(c => ({ method: c.method, headers: c.headers })),
  { method: 'POST', headers: oldWire }, { method: 'GET', headers: oldGetWire }])
check('the real guard ran (shared/http_guard.py in the stack Python)', verdicts !== null)
if (verdicts) {
  cases.forEach((c, i) => check(`guard: ${c.name} → ${c.wantText}`, c.want(verdicts[i]), verdicts[i]))
  const [oldPost, oldGet] = verdicts.slice(cases.length)
  check('negative control: the pre-fix POST mapping is ADMITTED (the bypass this fixes)', oldPost.allowed, oldPost)
  check('negative control: the pre-fix GET mapping is ADMITTED for any Host', oldGet.allowed, oldGet)
}

server.close()
console.log(`streamProxy.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
