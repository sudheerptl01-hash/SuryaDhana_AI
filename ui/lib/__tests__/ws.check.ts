/**
 * Live-quote socket lifecycle checks (PM request 25 Oct after the ui-api hang: 95 accepts, 0 closes): the REAL
 * lib/wsManager.ts singleton driven through lib/monitorLifecycle.ts (what AppProvider runs) against a fake
 * WebSocket, under plain node 25 (type stripping, no deps):
 *
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/ws.check.ts
 *
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as nodeModule from 'node:module'
import * as fs from 'node:fs'
import * as path from 'node:path'

;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
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
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── a fake WebSocket: records every socket, close code and send; the test drives open / close ───────────────
class FakeWS {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static all: FakeWS[] = []
  readyState = FakeWS.CONNECTING
  closeCode: number | null = null
  sent: string[] = []
  onopen: ((e: unknown) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onmessage: ((e: unknown) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeWS.all.push(this)
  }
  send(s: string): void {
    if (this.readyState !== FakeWS.OPEN) throw new Error('not open')
    this.sent.push(s)
  }
  close(code = 1005): void {
    if (this.readyState >= FakeWS.CLOSING) return
    this.closeCode = code
    // a socket closed while CONNECTING never opens; its close event reports 1006 (browser behaviour)
    this.readyState = FakeWS.CLOSING
    this.pendingCloseCode = this.wasOpen ? code : 1006
  }
  private wasOpen = false
  private pendingCloseCode: number | null = null
  /** server accepted */
  accept(): void {
    if (this.readyState !== FakeWS.CONNECTING) return
    this.readyState = FakeWS.OPEN
    this.wasOpen = true
    this.onopen?.({})
  }
  /** deliver the close event (late, as a real close handshake would) */
  finishClose(): void {
    if (this.readyState === FakeWS.CLOSED) return
    const code = this.pendingCloseCode ?? 1006
    this.readyState = FakeWS.CLOSED
    this.onclose?.({ code })
  }
  /** the server or the network drops it */
  drop(code = 1006): void {
    this.pendingCloseCode = code
    this.readyState = FakeWS.CLOSING
    this.finishClose()
  }
}
const g = globalThis as unknown as { WebSocket?: unknown }
g.WebSocket = FakeWS

const { monitorWS } = await import('../wsManager')
const { attachMonitorSocket } = await import('../monitorLifecycle')

const live = () => FakeWS.all.filter((s) => s.readyState === FakeWS.CONNECTING || s.readyState === FakeWS.OPEN)
// the first live socket, or an inert closed stand-in, so a regression is reported as FAILs instead of a TypeError
const NONE: FakeWS = Object.assign(Object.create(FakeWS.prototype) as FakeWS, { readyState: FakeWS.CLOSED, closeCode: null, sent: [] })
const first = (): FakeWS => live()[0] ?? NONE
const page = new EventTarget()
const URL_ = 'ws://127.0.0.1:8010/api/monitor/ws/monitor'
let status: boolean[] = []
const onStatus = (c: boolean) => status.push(c)
const pagehide = (persisted = true) => page.dispatchEvent(Object.assign(new Event('pagehide'), { persisted }))
const pageshow = (persisted: boolean) => page.dispatchEvent(Object.assign(new Event('pageshow'), { persisted }))

// 1. mount: one socket, opened once
const detach1 = attachMonitorSocket(page, monitorWS, URL_, onStatus)
monitorWS.addSymbols(['NIFTY', 'NSEI'])
check('mount opens exactly one socket', FakeWS.all.length === 1 && live().length === 1, FakeWS.all.length)
pageshow(false) // the first load's pageshow
check("first load's pageshow does not open a second socket", FakeWS.all.length === 1)
FakeWS.all[0].accept()
check('open → status true', status.at(-1) === true)
check('the symbol set is sent on open', FakeWS.all[0].sent.some((m) => m.includes('NIFTY')), FakeWS.all[0].sent)
monitorWS.connect(URL_)
check('a second connect() while OPEN opens nothing', FakeWS.all.length === 1)

// 2. React StrictMode-style unmount + mount: the first socket is closed cleanly (1000), one live socket remains
detach1()
check('unmount closes the socket with code 1000', FakeWS.all[0].closeCode === 1000, FakeWS.all[0].closeCode)
const detach2 = attachMonitorSocket(page, monitorWS, URL_, onStatus)
check('remount: one live socket', live().length === 1 && FakeWS.all.length === 2, FakeWS.all.map((s) => s.readyState))
FakeWS.all[1].accept()
status = []
FakeWS.all[0].finishClose() // the superseded socket's close event arrives late
check("a superseded socket's late close never marks the live socket down", status.every((x) => x === true), status)
check('…and opens no extra socket', live().length === 1 && FakeWS.all.length === 2)

// 3. page hide → clean close; show from the back-forward cache → exactly one new socket; repeated cycles never leak
let maxLive = live().length
for (let i = 0; i < 20; i++) {
  const before = FakeWS.all.length
  const cur = first()
  pagehide(true)
  check(`cycle ${i}: pagehide closes the socket with 1000`, cur.closeCode === 1000 && live().length === 0, cur.closeCode)
  pageshow(true)
  check(`cycle ${i}: pageshow (persisted) reopens exactly one`, FakeWS.all.length === before + 1 && live().length === 1)
  if (i % 2) cur.finishClose() // late close handshake on half the cycles
  first().accept()
  maxLive = Math.max(maxLive, live().length)
}
check('never more than one live socket per window across 20 hide/show cycles', maxLive === 1, maxLive)
status = []
for (const s of FakeWS.all.filter((x) => x.readyState === FakeWS.CLOSING)) s.finishClose()
check('late closes of all superseded sockets keep the status up', status.every((x) => x === true) || status.length === 0, status)
check('the live socket still receives the symbol set after the cycles', first().sent.some((m) => m.includes('NIFTY')))

// 4. a server-side drop reconnects with ONE socket (backoff timer), never two
const dropped = first()
dropped.drop(1006)
check('a drop leaves no live socket until the backoff fires', live().length === 0)
await new Promise((r) => setTimeout(r, 2100))
check('backoff reconnect opens exactly one socket', live().length === 1, live().length)
first().accept()

// 5. pagehide while CONNECTING, then unmount: nothing left open, no reconnect timer fires later
pagehide(true)
pageshow(true)
const connecting = first()
detach2()
check('unmount while CONNECTING closes it', connecting.closeCode === 1000 && live().length === 0)
connecting.finishClose() // reports 1006: must not schedule a reconnect after unmount
const n = FakeWS.all.length
await new Promise((r) => setTimeout(r, 2200))
check('no reconnect after unmount (even on a 1006 close)', FakeWS.all.length === n && live().length === 0, FakeWS.all.length - n)
pagehide(true)
pageshow(true)
check('listeners removed on unmount: hide/show do nothing', FakeWS.all.length === n)

// 6. wiring: AppProvider is the only place that opens the socket, through attachMonitorSocket
{
  const uiRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
  const ctx = fs.readFileSync(path.join(uiRoot, 'context/AppContext.tsx'), 'utf8')
  check('AppContext attaches the socket via attachMonitorSocket and detaches on cleanup',
    /attachMonitorSocket\(window, monitorWS, wsUrl, setWsConnected\)/.test(ctx) && /detach\(\)/.test(ctx) && !/monitorWS\.connect\(/.test(ctx))
  const users: string[] = []
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name.startsWith('.') || e.name === '__tests__') continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.tsx?$/.test(e.name)) {
        const src = fs.readFileSync(p, 'utf8')
        if (/new WebSocket\(|monitorWS\.connect\(/.test(src)) users.push(path.relative(uiRoot, p))
      }
    }
  }
  for (const d of ['app', 'components', 'context', 'lib']) walk(path.join(uiRoot, d))
  check('no other component opens a WebSocket (one per window)', JSON.stringify(users.sort()) === JSON.stringify(['lib/wsManager.ts']), users)
  const page = fs.readFileSync(path.join(uiRoot, 'app/page.tsx'), 'utf8')
  check('AppProvider wraps the page once, outside the per-page boundaries and the reload epoch',
    /<AppProvider>\s*<ToastProvider>/.test(page) && !/<AppProvider key=/.test(page))
}

// 7. a superseded socket's late close must not reach the LIVE socket's heartbeat or backoff. This is a wsManager.ts
//    defect (not owned here; W2-UI-SHELL patch request PR-WS1: ignore close events of a socket that is no longer
//    this.ws). White-box: reads the manager's private timers. Until the patch lands the checks assert the defect is
//    still reproduced (a negative control proving they can see it); once the guard is in the source they enforce it.
{
  const uiRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
  const wsSrc = fs.readFileSync(path.join(uiRoot, 'lib/wsManager.ts'), 'utf8')
  const patched = /if \(this\.ws !== sock\) return/.test(wsSrc)
  const m = monitorWS as unknown as { heartbeatTimer: unknown; reconnectTimer: unknown; reconnectDelay: number }
  const page7 = new EventTarget()
  const hide7 = () => page7.dispatchEvent(Object.assign(new Event('pagehide'), { persisted: true }))
  const show7 = () => page7.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }))
  const detach7 = attachMonitorSocket(page7, monitorWS, URL_, () => {})
  first().accept()
  // (a) heartbeat: the old socket was OPEN, so its late close is a clean 1000
  const s1 = first()
  hide7()
  show7()
  first().accept()
  check('7a: the new socket has a heartbeat before the late close', m.heartbeatTimer !== null)
  s1.finishClose()
  const hbAlive = m.heartbeatTimer !== null
  if (patched) check("7a: a superseded socket's late close keeps the live socket's heartbeat", hbAlive)
  else check('7a (negative control, PR-WS1 pending): the unpatched wsManager drops the live heartbeat', !hbAlive)
  // (b) backoff: the old socket was closed while CONNECTING, so its late close reports 1006
  hide7()
  show7()
  const s3 = first() // CONNECTING
  hide7()
  show7()
  first().accept()
  check('7b: the live socket resets the backoff on open', m.reconnectDelay === 2000 && m.reconnectTimer === null)
  s3.finishClose()
  const spurious = m.reconnectTimer !== null
  if (patched) check("7b: a superseded socket's late 1006 close schedules no reconnect", !spurious)
  else check('7b (negative control, PR-WS1 pending): the unpatched wsManager schedules a spurious reconnect', spurious)
  check('7: still exactly one live socket', live().length === 1, live().length)
  detach7()
  check('7: unmount leaves no socket and no timers', live().length === 0 && m.reconnectTimer === null && m.heartbeatTimer === null)
  if (!patched) console.log('ws.check: NOTE wsManager.ts PR-WS1 not applied: section 7 asserted the known defect')
}

// 8. LINK UP kicks a socket that waits on its backoff (R-UI-SHELL-10): the reconnected event reconnects at once with a
//    fresh 2 s backoff; never a second socket, never while open, hidden or unmounted.
{
  const { RECONNECTED_EVENT } = await import('../reconnect')
  const m = monitorWS as unknown as { reconnectTimer: unknown; reconnectDelay: number }
  const page8 = new EventTarget()
  const linkUp = () => page8.dispatchEvent(new Event(RECONNECTED_EVENT))
  const detach8 = attachMonitorSocket(page8, monitorWS, URL_, () => {})
  first().accept()
  const n8 = FakeWS.all.length
  linkUp()
  check('8: LINK UP while the socket is open opens nothing', FakeWS.all.length === n8 && live().length === 1)
  m.reconnectDelay = 16_000 // as after several failed attempts during a ui-api restart
  first().drop(1006)
  check('8: after a drop the manager waits on a long backoff (negative control)', live().length === 0 && m.reconnectTimer !== null)
  linkUp()
  check('8: LINK UP reconnects at once (one new socket)', live().length === 1 && FakeWS.all.length === n8 + 1, live().length)
  check('8: …with the backoff reset and its timer cancelled', m.reconnectDelay === 2000 && m.reconnectTimer === null, m.reconnectDelay)
  linkUp()
  check('8: a second LINK UP while CONNECTING opens nothing', FakeWS.all.length === n8 + 1)
  first().accept()
  page8.dispatchEvent(Object.assign(new Event('pagehide'), { persisted: true }))
  const n8b = FakeWS.all.length
  linkUp()
  check('8: LINK UP while the page is hidden (socket closed on purpose) opens nothing', FakeWS.all.length === n8b && live().length === 0)
  page8.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }))
  first().accept()
  detach8()
  const n8c = FakeWS.all.length
  linkUp()
  check('8: LINK UP after unmount opens nothing (listener removed)', FakeWS.all.length === n8c && live().length === 0)
  const src = fs.readFileSync(path.join(path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..'), 'lib/monitorLifecycle.ts'), 'utf8')
  check('8: the lifecycle listens to the reconnected event', /addEventListener\(RECONNECTED_EVENT, onReconnected\)/.test(src))
}

// ── 9. P10: the server's monitored set is re-filled after a Redis restart (round 4b) ─────────────────────────────
{
  const { missingMonitorSymbols, MONITOR_RESYNC_MS, MONITOR_RESYNC_HIDDEN_MS } = await import('../monitorLifecycle')
  const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
  check('9: Redis restarted (empty set): every watched symbol is re-subscribed', eq(missingMonitorSymbols(['TCS', 'INFY'], []), ['TCS', 'INFY']))
  check('9: only the missing ones, case-insensitively, each once, in watchlist order',
    eq(missingMonitorSymbols(['tcs', 'INFY', 'RELIANCE', 'INFY', ' hdfcbank '], ['TCS', 'reliance']), ['INFY', 'hdfcbank']))
  check('9: a full set needs nothing (no POST every 10 min in the normal case)', eq(missingMonitorSymbols(['TCS'], ['TCS', 'NIFTY']), []))
  check('9: an unknown answer (error body, missing field) re-subscribes nothing',
    eq(missingMonitorSymbols(['TCS'], undefined), []) && eq(missingMonitorSymbols(['TCS'], { detail: 'redis down' }), []) && eq(missingMonitorSymbols(['TCS'], null), []))
  check('9: junk entries are ignored', eq(missingMonitorSymbols(['TCS', 7 as unknown as string, ''], [null, 3, 'tcs']), []))
  check('9: cadence 10 min visible, 30 min hidden', MONITOR_RESYNC_MS === 600_000 && MONITOR_RESYNC_HIDDEN_MS === 1_800_000)
  const ctx = fs.readFileSync(path.join(path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..'), 'context/AppContext.tsx'), 'utf8')
  check('9: AppContext re-syncs on every socket REconnect (not the first connect) and on a 10 / 30 min poll',
    /if \(wsConnected && wsSeenRef\.current === 'down'\) void resyncMonitor\(\)/.test(ctx)
    && /usePolling\(resyncMonitor, hidden \? MONITOR_RESYNC_HIDDEN_MS : MONITOR_RESYNC_MS\)/.test(ctx))
  check('9: the resync reads the set once and subscribes only what is missing',
    /server = \(await monitorList\(\)\)\.data\?\.symbols/.test(ctx) && /for \(const t of missingMonitorSymbols\(list, server\)\) monitorSubscribe\(t\)/.test(ctx))
}

if (failed) {
  console.error(`ws.check: ${failed} failed, ${passed} passed`)
  process.exit(1)
}
console.log(`ws.check: all ${passed} checks pass`)
