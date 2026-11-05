/**
 * Unit checks for the desktop shell's pure modules (D4). No test framework is configured in ui/, so, like
 * ui/lib/__tests__/errors.check.ts, this file is type-checked by `tsc --noEmit` and executed directly by Node 25
 * (erasable TypeScript, no build step):
 *
 *     node ui/components/desktop/__tests__/desktop.check.ts
 *
 * Exits non-zero on the first failing group. Modules are imported by URL with their .ts extension (what Node
 * needs) and typed with `typeof import(...)` (what tsc needs).
 */
import * as nodeModule from 'node:module'

// extensionless relative imports between the pure modules (lib/liveEvidence.ts → ./feedState) resolve to their .ts
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

type SessionMod = typeof import('../session')
type PagesMod = typeof import('../pages')
type HealthMod = typeof import('../health')
type BuildMod = typeof import('../build')
type ChunkMod = typeof import('../chunkRecovery')
type LocationMod = typeof import('../location')
type StatusMod = typeof import('../status')
type ZoomMod = typeof import('../zoom')
type HolidayStoreMod = typeof import('../holidayStore')
type ClientErrorsMod = typeof import('../../../lib/clientErrors')
type DeepLinkMod = typeof import('../../../lib/deepLink')
type ShortcutsMod = typeof import('../../../lib/shortcuts')
type ReconnectMod = typeof import('../../../lib/reconnect')
type SharedFetchMod = typeof import('../../../lib/sharedFetch')
type FeedStateMod = typeof import('../../../lib/feedState')
type GoAliasesMod = typeof import('../../../lib/goAliases')
type LiveEvidenceMod = typeof import('../../../lib/liveEvidence')
type RefreshStatusMod = typeof import('../../../lib/refreshStatus')
type IciciStatusMod = typeof import('../../../lib/iciciStatus')
type DownloadTextMod = typeof import('../../../lib/downloadText')
type FindMod = typeof import('../find')

const load = async <T,>(rel: string): Promise<T> => (await import(new URL(rel, import.meta.url).href)) as T

let failures = 0
let passes = 0
function check(name: string, cond: boolean, detail = ''): void {
  if (cond) { passes++; return }
  failures++
  console.error(`FAIL ${name}${detail ? ` — ${detail}` : ''}`)
}
const eq = (name: string, got: unknown, want: unknown) =>
  check(name, JSON.stringify(got) === JSON.stringify(want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)

/** UTC epoch ms for an IST wall-clock time. */
const ist = (iso: string) => Date.parse(`${iso}+05:30`)

async function sessionChecks(): Promise<void> {
  const S = await load<SessionMod>('../session.ts')
  // 24 Oct 2026 is a Saturday; 26 Oct a Monday; 10 Nov a Tuesday (Diwali-Balipratipada, NSE closed)
  eq('ist parts', S.istParts(ist('2026-10-26T09:14:59')), { date: '2026-10-26', time: '09:14:59', weekday: 1, minutes: 554, seconds: 59 })
  eq('ist date rolls at IST midnight, not UTC', S.istParts(Date.parse('2026-10-25T18:30:00Z')).date, '2026-10-26')
  eq('saturday closed', [S.nseSession(ist('2026-10-24T11:10:00')).state, S.nseSession(ist('2026-10-24T11:10:00')).reason], ['CLOSED', 'WEEKEND'])
  eq('sunday closed', S.nseSession(ist('2026-10-25T10:00:00')).reason, 'WEEKEND')
  const cases: Array<[string, string, string | null]> = [
    ['2026-10-26T08:59:59', 'CLOSED', 'BEFORE OPEN'],
    ['2026-10-26T09:00:00', 'PRE-OPEN', null],
    ['2026-10-26T09:14:59', 'PRE-OPEN', null],
    ['2026-10-26T09:15:00', 'OPEN', null],
    ['2026-10-26T15:29:59', 'OPEN', null],
    ['2026-10-26T15:30:00', 'CLOSED', 'AFTER CLOSE'],
    ['2026-10-26T23:59:59', 'CLOSED', 'AFTER CLOSE'],
  ]
  for (const [t, st, reason] of cases) {
    const s = S.nseSession(ist(t))
    eq(`session ${t}`, [s.state, s.reason], [st, reason])
  }
  const hol = S.holidaysFromEco([
    { date: '2026-11-10', kind: 'HOLIDAY', what: 'NSE closed · Diwali-Balipratipada' },
    { date: '2026-11-11', kind: 'CPI', what: 'India CPI' },
    { date: 'bad', kind: 'HOLIDAY', what: 'x' },
    { kind: 'HOLIDAY' },
  ])
  eq('holiday parse', [...hol.entries()], [['2026-11-10', 'Diwali-Balipratipada']])
  const h = S.nseSession(ist('2026-11-10T10:00:00'), hol)
  eq('holiday closes the session', [h.state, h.reason, h.holiday], ['CLOSED', 'HOLIDAY', 'Diwali-Balipratipada'])
  eq('no holidays → weekday rule', S.nseSession(ist('2026-11-10T10:00:00'), null).state, 'OPEN')
  eq('holidaysFromEco tolerates null', S.holidaysFromEco(null).size, 0)

  // C3-06: ONE session rule for the title strip and the page header (MarketCommandHeader)
  const hdr = (t: string, hl: ReadonlyMap<string, string> | null = hol) => S.headerSession(S.nseSession(ist(t), hl))
  eq('2026-11-10 10:00 IST: header says HOLIDAY (was NSE OPEN)', [hdr('2026-11-10T10:00:00').label, hdr('2026-11-10T10:00:00').holiday],
    ['HOLIDAY', 'Diwali-Balipratipada'])
  eq('2026-11-10 10:00 IST: strip says CLOSED · HOLIDAY', [h.state, h.reason], ['CLOSED', 'HOLIDAY'])
  eq('header keeps its wording on a trading day', ['08:59:59', '09:00:00', '09:15:00', '15:29:59', '15:30:00', '15:59:59', '16:00:00']
    .map(x => hdr(`2026-10-26T${x}`).label), ['CLOSED', 'PRE-OPEN', 'NSE OPEN', 'NSE OPEN', 'CLOSING', 'CLOSING', 'CLOSED'])
  eq('header weekend', [hdr('2026-10-24T11:00:00').label, hdr('2026-10-25T10:00:00').label], ['WEEKEND', 'WEEKEND'])
  eq('header tones', [hdr('2026-10-26T10:00:00').tone, hdr('2026-10-26T09:05:00').tone, hdr('2026-11-10T10:00:00').tone], ['green', 'amber', 'muted'])
  // header and strip agree on open / pre-open / closed at every minute of a holiday week, with and without holidays
  let disagree = 0
  for (const hl of [hol, null]) {
    for (let t = ist('2026-11-08T00:00:00'); t < ist('2026-11-13T00:00:00'); t += 60_000) {
      const strip = S.nseSession(t, hl)
      const head = S.headerSession(strip).label
      const want = strip.state === 'OPEN' ? 'NSE OPEN' : strip.state === 'PRE-OPEN' ? 'PRE-OPEN' : null
      if (want ? head !== want : (head === 'NSE OPEN' || head === 'PRE-OPEN')) disagree++
    }
  }
  check('header and strip never disagree (5 days × 1440 min × 2)', disagree === 0, `${disagree} minutes disagree`)
  const fs = await import('node:fs')
  const header = fs.readFileSync(new URL('../../MarketCommandHeader.tsx', import.meta.url), 'utf8')
  check('MarketCommandHeader uses the shared session rule + holiday fetch',
    /headerSession\(nseSession\(/.test(header) && /useNseHolidays\(/.test(header))
  check('MarketCommandHeader no longer has its own weekday-only rule', !/getDay\(\) === 0|d === 0 \|\| d === 6/.test(header))
  const strip = fs.readFileSync(new URL('../TitleStrip.tsx', import.meta.url), 'utf8')
  check('TitleStrip uses the shared holiday fetch (one request per window)', /from '\.\/holidays'/.test(strip) && !/eco-calendar/.test(strip))
}

async function statusChecks(): Promise<void> {
  const S = await load<StatusMod>('../status.ts')
  // C1-desktop-native-03: never grey between two normal pushes; grey after ~3 missed ones
  check('stale threshold covers 3 shell intervals', S.STATUS_STALE_MS >= 3 * S.SHELL_STATUS_MAX_INTERVAL_MS, String(S.STATUS_STALE_MS))
  check('stale threshold below 4 intervals (still noticed)', S.STATUS_STALE_MS < 4 * S.SHELL_STATUS_MAX_INTERVAL_MS + 1, String(S.STATUS_STALE_MS))
  check('pull before the threshold', S.STATUS_PULL_MS < S.STATUS_STALE_MS)
  // the old 20 s threshold went grey 15 s into the old 30–35 s heartbeat; with pulls every 10 s nothing goes grey
  const rx = Date.parse('2026-10-25T06:00:00Z')
  for (const gap of [10_000, 20_000, 30_000, 34_999]) check(`fresh ${gap / 1000} s after a push`, !S.isStatusStale(S.statusFreshAt('2026-10-25T06:00:00Z', rx), rx + gap))
  check('stale after 3 missed 10 s pushes + jitter', S.isStatusStale(S.statusFreshAt('2026-10-25T06:00:00Z', rx), rx + 35_001))
  check('no status yet = stale', S.isStatusStale(0, rx))
  eq('freshness = the poller time, not the arrival time', S.statusFreshAt('2026-10-25T05:59:58Z', rx), rx - 2000)
  check('a cached status from a stopped poller goes stale even when pulled just now',
    S.isStatusStale(S.statusFreshAt('2026-10-25T05:59:00Z', rx), rx))
  eq('a future `at` is capped at the arrival time', S.statusFreshAt('2026-10-25T06:05:00Z', rx), rx)
  eq('missing / bad `at` → arrival time', [S.statusFreshAt(undefined, rx), S.statusFreshAt('nope', rx)], [rx, rx])
  const fs = await import('node:fs')
  // cross-language contract with the shell (desktop/src-tauri/src/health.rs STATUS_HEARTBEAT): it pushes at least
  // every SHELL_STATUS_MAX_INTERVAL_MS, so ~3 pushes always fit inside the stale threshold
  const rust = fs.readFileSync(new URL('../../../../desktop/src-tauri/src/health.rs', import.meta.url), 'utf8')
  const hb = /STATUS_HEARTBEAT:\s*Duration\s*=\s*Duration::from_secs\((\d+)\)/.exec(rust)
  check('shell heartbeat found (health.rs STATUS_HEARTBEAT)', !!hb)
  if (hb) {
    const ms = Number(hb[1]) * 1000
    check(`shell heartbeat ${ms / 1000} s ≤ the UI contract ${S.SHELL_STATUS_MAX_INTERVAL_MS / 1000} s`, ms <= S.SHELL_STATUS_MAX_INTERVAL_MS)
    check('3 heartbeats + one 5 s poll tick fit inside the stale threshold', 3 * ms + 5_000 <= S.STATUS_STALE_MS)
  }
  const shell = fs.readFileSync(new URL('../PlatformShell.tsx', import.meta.url), 'utf8')
  check('PlatformShell no longer has its own 20 s threshold', !/STATUS_STALE_MS = 20_000/.test(shell) && /isStatusStale\(/.test(shell))
  check('PlatformShell pulls shell_status when pushes stop', /STATUS_PULL_MS/.test(shell))
}

async function pagesChecks(): Promise<void> {
  const P = await load<PagesMod>('../pages.ts')
  const fs = await import('node:fs')
  const src = fs.readFileSync(new URL('../../../app/page.tsx', import.meta.url), 'utf8')
  const block = /const COMMAND_PAGES: CommandPage\[\] = \[([\s\S]*?)\n\]/.exec(src)?.[1] ?? ''
  const rows = [...block.matchAll(/\{\s*id:\s*'([^']+)',\s*code:\s*'([^']+)',\s*label:\s*'((?:[^'\\]|\\.)*)'/g)]
    .map(m => [m[1], m[2], m[3].replace(/\\'/g, "'")])
  check('page.tsx parsed (43 pages)', rows.length === 43, `parsed ${rows.length}`)
  const mine = Object.entries(P.PAGE_META).map(([id, m]) => [id, m.code, m.label])
  eq('PAGE_META matches COMMAND_PAGES (order, id, code, label)', mine, rows)
  eq('tabFromSearch', [P.tabFromSearch('?tab=desk'), P.tabFromSearch('?tab=nope'), P.tabFromSearch(''), P.tabFromSearch('?x=1&tab=risk')],
    ['desk', 'brief', 'brief', 'risk'])
  eq('window title pattern', P.windowTitle(P.pageMeta('desk')), 'DESK · Decision Desk — SuryaDhana')
  eq('unknown id falls back to the document.title code', P.pageMeta('newpage', 'NEWP · SuryaDhana'), { code: 'NEWP', label: '' })
  check('titles ≤ 120 chars', Object.keys(P.PAGE_META).every(id => P.windowTitle(P.pageMeta(id)).length <= 120))
  check('long label clipped', P.windowTitle({ code: 'X', label: 'y'.repeat(300) }).length === 120)

  // CT-13: the strip's BRF label follows the page's own time-of-day title (Brief.tsx), never MORNING over EVENING
  const hm = (h: number, m: number) => h * 60 + m
  eq('briefTitle: Fri 10:00 / Fri 16:03 / Sun 16:03 / Sun 02:00 / Sun 10:00 / Mon 09:14 / Mon 15:29',
    [P.briefTitle(5, hm(10, 0)), P.briefTitle(5, hm(16, 3)), P.briefTitle(0, hm(16, 3)), P.briefTitle(0, hm(2, 0)),
     P.briefTitle(0, hm(10, 0)), P.briefTitle(1, hm(9, 14)), P.briefTitle(1, hm(15, 29))],
    ['Session brief', 'Evening brief', 'Evening brief', 'Overnight brief', 'Morning brief', 'Morning brief', 'Session brief'])
  eq('stripLabel: BRF is dynamic, other pages keep their label',
    [P.stripLabel(P.pageMeta('brief'), 0, hm(16, 3)), P.stripLabel(P.pageMeta('desk'), 0, hm(16, 3))], ['Evening brief', 'Decision Desk'])
  const brief = fs.readFileSync(new URL('../../Brief.tsx', import.meta.url), 'utf8')
  check('Brief.tsx header rule unchanged (same thresholds and titles as briefTitle; update both together)',
    brief.includes('istDay >= 1 && istDay <= 5 && istHM >= 915 && istHM < 1530 ? "Session Brief" : istHM >= 1530 ? "Evening Brief" : istHM < 400 ? "Overnight Brief" : "Morning Brief"'))
  const shellSrc = fs.readFileSync(new URL('../PlatformShell.tsx', import.meta.url), 'utf8')
  check('strip + native window title use stripLabel (minute tick only while BRF is shown)',
    /stripLabel\(pageMetaNow, p\.weekday, p\.minutes\)/.test(shellSrc) && /useMinuteWhile\(desktop && tab === 'brief'\)/.test(shellSrc)
    && /windowTitle\(meta\)/.test(shellSrc) && /<TitleStrip meta=\{meta\}/.test(shellSrc))
}

async function healthChecks(): Promise<void> {
  const H = await load<HealthMod>('../health.ts')
  eq('backoff schedule', [0, 1, 2, 3, 4, 5, 50].map(H.nextDelayMs), [10_000, 2_000, 5_000, 10_000, 15_000, 15_000, 15_000])
  let s = { state: 'unknown' as const, failures: 0, lastOkAt: null, since: 0, latencyMs: null, nextProbeAt: null } as import('../health').HealthSnapshot
  s = H.reduceProbe(s, true, 1000, 3)
  eq('ok → up', [s.state, s.failures, s.lastOkAt, s.since], ['up', 0, 1000, 1000])
  s = H.reduceProbe(s, false, 2000, null)
  eq('one failure is not down yet (confirm probe)', [s.state, s.failures], ['up', 1])
  s = H.reduceProbe(s, false, 4000, null)
  eq('second failure → down, since = flip time', [s.state, s.failures, s.since], ['down', 2, 4000])
  s = H.reduceProbe(s, false, 9000, null)
  eq('stays down, since unchanged', [s.state, s.since], ['down', 4000])
  s = H.reduceProbe(s, true, 12000, 4)
  eq('recovers', [s.state, s.failures, s.since], ['up', 0, 12000])

  // probe mode latch with a fake fetch
  const realFetch = globalThis.fetch
  const answers: Record<string, () => Promise<Response>> = {}
  globalThis.fetch = ((url: string) => (answers[url] ?? (() => Promise.reject(new TypeError('network'))))()) as typeof fetch
  const json = (status: number) => () => Promise.resolve(new Response('{}', { status, headers: { 'content-type': 'application/json' } }))
  const html = (status: number) => () => Promise.resolve(new Response('<html>', { status, headers: { 'content-type': 'text/html' } }))
  type Mode = 'api' | 'health' | 'api-any'
  const asked: string[] = []
  globalThis.fetch = ((url: string) => { asked.push(url); return (answers[url] ?? (() => Promise.reject(new TypeError('network'))))() }) as typeof fetch
  try {
    // C3-09: /api/health first (ui-api's alias; reaches ui-api through :8010 and through Next's /api rewrite)
    const st = { mode: 'api' as Mode }
    answers['/api/health'] = json(200)
    check('/api/health 200 json → up', await H.probeUiApi(st))
    eq('stays on /api/health, one request per probe', [st.mode, asked], ['api', ['/api/health']])
    asked.length = 0
    answers['/api/health'] = html(500)
    check('/api/health 5xx → down', !(await H.probeUiApi(st)))
    eq('5xx never changes the latched path', st.mode, 'api')
    delete answers['/api/health']
    check('network error → down', !(await H.probeUiApi(st)) && st.mode === 'api')
    // a ui-api without the alias yet: its JSON 404 proves it is alive, then /health from now on (no 404 per probe)
    const old = { mode: 'api' as Mode }
    answers['/api/health'] = json(404)
    answers['/health'] = json(200)
    asked.length = 0
    check('older ui-api (JSON 404) → alive', await H.probeUiApi(old))
    eq('latched to /health', old.mode, 'health')
    asked.length = 0
    check('older ui-api: /health 200 → up', await H.probeUiApi(old))
    eq('older ui-api: steady state probes /health only', asked, ['/health'])
    answers['/health'] = json(503)
    check('/health 5xx → down without latching', !(await H.probeUiApi(old)) && old.mode === 'health')
    // Next :3000 in front of that older ui-api: /health is Next's HTML 404 → any JSON from /api/health
    const next = { mode: 'health' as Mode }
    answers['/health'] = html(404)
    answers['/api/health'] = json(404)
    check('Next front (404 html) → /api JSON 404 = ui-api alive', await H.probeUiApi(next))
    eq('mode latched to api-any', next.mode, 'api-any')
    answers['/api/health'] = html(500)
    check('Next proxy 500 → down', !(await H.probeUiApi(next)))
    // the monitor's first probe goes to /api/health (fails without the fix: it used to start on /health)
    const g = globalThis as unknown as { window?: unknown; document?: unknown }
    const prev = [g.window, g.document]
    g.window = new EventTarget()
    g.document = Object.assign(new EventTarget(), { hidden: false })
    try {
      const modes: string[] = []
      const m = new H.HealthMonitor(s => { modes.push(s.mode); return Promise.resolve(true) })
      m.start()
      await new Promise(r => setTimeout(r, 0))
      m.stop()
      eq('HealthMonitor starts on /api/health', modes, ['api'])
    } finally {
      [g.window, g.document] = prev
    }
  } finally {
    globalThis.fetch = realFetch
  }
}

async function buildChecks(): Promise<void> {
  const B = await load<BuildMod>('../build.ts')
  eq('normalizeBuild', ['20261024-111000-a1b2c3d', 'unversioned', '', 'dev', 'bad id!', 7, null].map(B.normalizeBuild),
    ['20261024-111000-a1b2c3d', null, null, null, null, null, null])
  eq('shortBuild release id', B.shortBuild('20261024-111000-a1b2c3d'), '1024·1110 a1b2c3d')
  eq('shortBuild null → DEV', B.shortBuild(null), 'DEV')
  eq('isNewBuild', [
    B.isNewBuild('20261024-120000-bbbbbbb', '20261024-111000-a1b2c3d'),
    B.isNewBuild('20261024-111000-a1b2c3d', '20261024-111000-a1b2c3d'),
    B.isNewBuild('20261024-120000-bbbbbbb', null),
    B.isNewBuild('unversioned', '20261024-111000-a1b2c3d'),
  ], [true, false, false, false])
}

async function chunkChecks(): Promise<void> {
  const store = new Map<string, string>()
  const fakeStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  }
  const g = globalThis as unknown as { window?: unknown }
  const prevWindow = g.window
  g.window = { sessionStorage: fakeStorage, location: { reload() {} } }
  const realFetch = globalThis.fetch
  try {
    const C = await load<ChunkMod>('../chunkRecovery.ts')
    const yes = [
      Object.assign(new Error('Loading chunk 6402 failed.\n(error: http://127.0.0.1:8010/_next/static/chunks/6402.js)'), { name: 'ChunkLoadError' }),
      new Error('Loading CSS chunk app/page failed'),
      new TypeError('Failed to fetch dynamically imported module: http://x/_next/a.js'),
      new TypeError('Importing a module script failed.'),
      'ChunkLoadError: Loading chunk 12 failed',
    ]
    const no = [new Error('Network Error'), new TypeError('Load failed'), null, undefined, 42, { message: 'boom' }]
    check('chunk errors detected', yes.every(C.isChunkLoadError))
    check('other errors ignored', no.every(e => !C.isChunkLoadError(e)))
    check('reload allowed initially', C.canAutoReload(1_000_000))
    let reloads = 0
    globalThis.fetch = (() => Promise.reject(new TypeError('network'))) as typeof fetch
    eq('server down → unreachable, no reload', [await C.recoverFromChunkError(() => { reloads++ }), reloads], ['unreachable', 0])
    globalThis.fetch = (() => Promise.resolve(new Response('', { status: 404 }))) as typeof fetch
    eq('server answers (even 404) → reloading', [await C.recoverFromChunkError(() => { reloads++ }), reloads], ['reloading', 1])
    eq('second chunk error inside the guard window → guarded', [await C.recoverFromChunkError(() => { reloads++ }), reloads], ['guarded', 1])
    check('guard expires after RELOAD_GUARD_MS', C.canAutoReload(Date.now() + C.RELOAD_GUARD_MS + 1))
    g.window = { get sessionStorage(): Storage { throw new Error('blocked') }, location: { reload() {} } }
    check('no storage → never auto-reload (no loop guard)', !C.canAutoReload())
  } finally {
    globalThis.fetch = realFetch
    g.window = prevWindow
  }
}

async function locationChecks(): Promise<void> {
  const calls: string[] = []
  const win = Object.assign(new EventTarget(), {
    history: {
      pushState(_s: unknown, _t: string, u?: string) { calls.push(`push ${u}`) },
      replaceState(_s: unknown, _t: string, u?: string) { calls.push(`replace ${u}`); return 'ret' },
    },
  })
  const g = globalThis as unknown as { window?: unknown }
  const prevWindow = g.window
  g.window = win
  try {
    const L = await load<LocationMod>('../location.ts')
    let events = 0
    const off = L.onLocationChange(() => { events++ })
    L.installLocationWatcher()
    L.installLocationWatcher() // idempotent: must not double-wrap
    const ret = (win.history.replaceState as (...a: unknown[]) => unknown)(null, '', '/?tab=desk')
    win.history.pushState(null, '', '/?tab=risk')
    win.dispatchEvent(new Event('popstate'))
    eq('call-through order', calls, ['replace /?tab=desk', 'push /?tab=risk'])
    eq('return value preserved', ret, 'ret')
    eq('one event per change (no double wrap) + popstate', events, 3)
    off()
    win.history.pushState(null, '', '/?tab=x')
    eq('unsubscribe works', events, 3)
  } finally {
    g.window = prevWindow
  }
}


// ── wave 2 shell (W2-UI-SHELL) ────────────────────────────────────────────────────────────────────────────

const read = async (rel: string): Promise<string> => (await import('node:fs')).readFileSync(new URL(rel, import.meta.url), 'utf8')

async function clientErrorChecks(): Promise<void> {
  const E = await load<ClientErrorsMod>('../../../lib/clientErrors.ts')
  // K1 body: clipped, control characters removed, url = path + query only, kind and tab carried
  const big = new Error(`boom\u0007${'x'.repeat(5000)}`)
  big.stack = `Error: boom\n    at render (http://127.0.0.1:8010/_next/static/chunks/a.js:1:2)\n${'    at f (x.js:1:1)\n'.repeat(500)}`
  const r = E.buildReport({ error: big, kind: 'render', tab: 'brief', build: '20261025-135500-0ae66db',
    href: 'http://127.0.0.1:8010/?tab=brief&sym=TCS#frag', extraStack: '\n    in Brief\n    in TabErrorBoundary' })
  check('K1 message clipped', r.message.length <= E.LIMITS.message && r.message.endsWith('…'), String(r.message.length))
  check('K1 control characters removed', !/[\u0000-\u0008]/.test(r.message))
  check('K1 stack clipped and carries the component stack', !!r.stack && r.stack.length <= E.LIMITS.stack)
  eq('K1 url = path + query, no origin, no fragment', r.url, '/?tab=brief&sym=TCS')
  eq('K1 kind / tab / build', [r.kind, r.tab, r.build], ['render', 'brief', '20261025-135500-0ae66db'])
  check('K1 JSON body stays under the server cap (8 KB)', new TextEncoder().encode(JSON.stringify(r)).length < 8 * 1024,
    String(new TextEncoder().encode(JSON.stringify(r)).length))
  eq('K1 only contract fields', Object.keys(r).sort(), ['build', 'kind', 'message', 'stack', 'tab', 'url'])
  const s1 = E.buildReport({ error: 'plain string', kind: 'rejection' })
  eq('K1 minimal report has no empty optional fields', s1, { message: 'plain string', kind: 'rejection' })
  eq('K1 non-errors are printable', [E.errorParts({ message: 'm' }).message, E.errorParts(42).message, E.errorParts(null).message], ['m', '42', 'null'])
  eq('K1 TypeError name kept', E.errorParts(new TypeError('x is not a function')).message, 'TypeError: x is not a function')
  check('K1 noise filtered', E.isNoise({ message: 'ResizeObserver loop completed with undelivered notifications.' })
    && E.isNoise({ message: 'Script error.' }) && E.isNoise({ message: 'x', stack: 'at chrome-extension://abc/x.js:1:1' })
    && !E.isNoise({ message: 'TypeError: a.filter is not a function' }))
  // gate: dedupe per fingerprint for DEDUPE_MS, ≤ MAX_PER_MINUTE per rolling minute, ≤ MAX_PER_PAGE per page
  const g = new E.ReportGate()
  const t0 = 1_000_000
  check('gate: first report allowed', g.allow('a', t0))
  check('gate: duplicate within the window refused', !g.allow('a', t0 + 1000))
  check('gate: duplicate after the window allowed', g.allow('a', t0 + E.DEDUPE_MS + 1))
  const g2 = new E.ReportGate()
  let ok = 0
  for (let i = 0; i < 30; i++) if (g2.allow(`f${i}`, t0 + i)) ok++
  eq('gate: rate limited to MAX_PER_MINUTE', ok, E.MAX_PER_MINUTE)
  check('gate: rate window rolls', g2.allow('later', t0 + 61_000))
  const g3 = new E.ReportGate()
  let total = 0
  for (let i = 0; i < 200; i++) if (g3.allow(`p${i}`, t0 + i * 10_000)) total++
  eq('gate: per-page cap', total, E.MAX_PER_PAGE)
  check('fingerprint separates kinds and frames', E.fingerprint({ message: 'm', kind: 'render', stack: 'at a (x.js:1:1)' })
    !== E.fingerprint({ message: 'm', kind: 'error', stack: 'at a (x.js:1:1)' }))
  // runtime path with a fake window: posts once, never in readonly QA mode, never throws
  const g4 = globalThis as unknown as { window?: unknown; fetch?: unknown }
  const prev = [g4.window, g4.fetch]
  const posts: Array<{ url: string; body: string }> = []
  const store = new Map<string, string>()
  g4.window = Object.assign(new EventTarget(), {
    location: { href: 'http://127.0.0.1:8010/?tab=desk', search: '?tab=desk', protocol: 'http:' },
    localStorage: { getItem: (k: string) => store.get(k) ?? null },
  })
  g4.fetch = ((url: string, init: RequestInit) => { posts.push({ url, body: String(init.body) }); return Promise.resolve(new Response(null, { status: 204 })) }) as typeof fetch
  try {
    const crash = new Error('render crash')         // a render loop re-throws the same error from the same frame
    const e1 = E.reportClientError(crash, { kind: 'render' })
    check('runtime: reported and POSTed to /api/client-errors', !!e1?.sent && posts.length === 1 && posts[0].url === E.CLIENT_ERRORS_URL)
    eq('runtime: tab defaults to the URL', JSON.parse(posts[0].body).tab, 'desk')
    check('runtime: duplicate not re-posted', E.reportClientError(crash, { kind: 'render' }) === null && posts.length === 1)
    store.set(E.QA_MODE_KEY, 'readonly')
    const e2 = E.reportClientError(new Error('qa context'), { kind: 'error' })
    check('runtime: readonly QA mode records but never POSTs', !!e2 && e2.sent === false && posts.length === 1)
    check('runtime: log + version', E.clientErrorLog().length === 2 && E.clientErrorsVersion() >= 2)
    E.clearClientErrors()
    check('runtime: clear', E.clientErrorLog().length === 0)
    const off = E.installClientErrorReporting()
    check('runtime: install is idempotent', E.installClientErrorReporting() === off)
    off()
  } finally {
    [g4.window, g4.fetch] = prev
  }
}

async function deepLinkChecks(): Promise<void> {
  const D = await load<DeepLinkMod>('../../../lib/deepLink.ts')
  const tabs = ['brief', 'desk', 'charts', 'options']
  eq('sym normalized + validated', ['tcs', ' M&M ', 'BAJAJ-AUTO', 'TCS.NS', 'bad sym', '', 'A'.repeat(21), null, '<x>'].map(D.normalizeSym),
    ['TCS', 'M&M', 'BAJAJ-AUTO', 'TCS.NS', null, null, null, null, null])
  eq('parseLocation tab + sym', D.parseLocation('?tab=charts&sym=tcs', tabs, 'brief'), { tab: 'charts', sym: 'TCS' })
  eq('parseLocation unknown tab → landing, bad sym dropped', D.parseLocation('?tab=nope&sym=%3Cscript%3E', tabs, 'brief'), { tab: 'brief', sym: null })
  eq('parseLocation M&M (encoded)', D.parseLocation('?tab=desk&sym=M%26M', tabs, 'brief').sym, 'M&M')
  eq('buildSearch keeps other params, sets/removes sym', [D.buildSearch('?x=1&tab=brief', 'desk', 'TCS'), D.buildSearch('?tab=desk&sym=TCS&x=1', 'desk', null)],
    ['?x=1&tab=desk&sym=TCS', '?tab=desk&x=1'])
  check('history state shape', D.isTerminalState({ sd: 1, tab: 'desk', sym: null, pushed: true }) && !D.isTerminalState({ tab: 'desk' }) && !D.isTerminalState(null))
  // closing a stock window: Back only when THIS page pushed it (a deep-linked one is removed in place, never by leaving)
  eq('close pushed stock window → back', D.closeStockAction({ sd: 1, tab: 'desk', sym: 'TCS', pushed: true }, 'TCS'), 'back')
  eq('close deep-linked stock window → replace', D.closeStockAction({ sd: 1, tab: 'desk', sym: 'TCS', pushed: false }, 'TCS'), 'replace')
  eq('close without a terminal state → replace', D.closeStockAction(null, 'TCS'), 'replace')
  eq('close when the entry has no sym → replace', D.closeStockAction({ sd: 1, tab: 'desk', sym: null, pushed: true }, null), 'replace')
  // page.tsx wiring (source guards; fail on the pre-wave-2 page)
  const page = await read('../../../app/page.tsx')
  check('page.tsx pushes a history entry per page switch (was replaceState only)', /history\.pushState\(st, '', buildSearch\(window\.location\.search, t, null\)\)/.test(page))
  check('page.tsx handles popstate (Back / Forward, ⌘[ / ⌘])', /addEventListener\('popstate', onPop\)/.test(page))
  check('page.tsx opens ?sym= deep links on load', /useState<string \| null>\(\(\) => initialLocation\(\)\.sym\)/.test(page))
  check('page.tsx initial page from the URL in the initializer (no first render on the brief)', /useState<Tab>\(\(\) => initialLocation\(\)\.tab\)/.test(page))
}

async function shortcutChecks(): Promise<void> {
  const K = await load<ShortcutsMod>('../../../lib/shortcuts.ts')
  const key = (k: string, o: Partial<import('../../../lib/shortcuts').KeyFacts> = {}) =>
    ({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, defaultPrevented: false, ...o })
  const free = { typing: false, blocked: false }
  eq('type-to-GO: a letter opens GO seeded with it (upper-cased)', K.typeToGoChar(key('t'), free), 'T')
  eq('type-to-GO: a digit too', K.typeToGoChar(key('5'), free), '5')
  eq('type-to-GO: never while typing in a field', K.typeToGoChar(key('t'), { typing: true, blocked: false }), null)
  eq('type-to-GO: never over another dialog', K.typeToGoChar(key('t'), { typing: false, blocked: true }), null)
  eq('type-to-GO: chords and consumed keys left alone',
    [key('k', { metaKey: true }), key('1', { altKey: true }), key('c', { ctrlKey: true }), key('j', { defaultPrevented: true }),
     key('N', { shiftKey: true }), key('a', { isComposing: true }), key('a', { repeat: true })].map(e => K.typeToGoChar(e, free)),
    [null, null, null, null, null, null, null])
  eq('type-to-GO: non-ticker keys ignored', ['/', '?', ' ', 'Enter', 'Escape', 'ArrowDown', 'F5', 'é'].map(k => K.typeToGoChar(key(k), free)),
    [null, null, null, null, null, null, null, null])
  const app = K.helpKeys(true).map(r => r[0]).join(' | ')
  const web = K.helpKeys(false).map(r => r[0]).join(' | ')
  check('help in the app teaches ⌘1–9, ⌘[ ⌘], ⌘N ⌘W and zoom', /⌘ 1 … 9/.test(app) && /⌘ \[/.test(app) && /⌘ N/.test(app) && /⌘ =/.test(app), app)
  check('help in a browser teaches Alt 1…0 and browser history', /Alt 1 … 0/.test(web) && /Alt ←/.test(web) && !/⌘ N/.test(web), web)
  check('help: Esc closes the stock window', K.helpKeys(true).some(([k, v]) => k === 'Esc' && /stock window/.test(v)))
  check('footer hint per host', /⌘1…9/.test(K.footerHint(true)) && /ALT\+1…0/.test(K.footerHint(false)))
  eq('page-strip tooltips', [K.tabKeyHint(0, true), K.tabKeyHint(0, false), K.tabKeyHint(9, true), K.tabKeyHint(10, false)],
    ['⌘1 · Alt+1', 'Alt+1', 'Alt+0', undefined])
  // wiring: the GO bar owns type-to-GO; the stock window closes on Esc (source guards, fail before wave 2)
  const bar = await read('../../CommandBar.tsx')
  check('CommandBar seeds GO from typeToGoChar', /typeToGoChar\(e, \{/.test(bar) && /show\(ch\)/.test(bar))
  check('CommandBar: Shift+Enter opens a new window', /run\(items\[sel\], e\.shiftKey\)/.test(bar) && /newWindow\(currentTab, it\.t\)/.test(bar))
  check('CommandBar help is host-aware (no fixed Alt-only table)', /helpKeys\(desktop, /.test(bar) && !/\['Alt 1 … 0', 'Jump to the first ten pages'\],\n  \['Shift N'/.test(bar))
  const modal = await read('../../StockDetailModal.tsx')
  check('StockDetailModal closes on Esc', /useEscapeToClose\(!!ticker, onClose\)/.test(modal) && /e\.key !== 'Escape'/.test(modal))
  check('StockDetailModal is a dialog the type-to-GO rule recognises', /data-sd-stock-window=""/.test(modal))
}

async function reconnectChecks(): Promise<void> {
  const R = await load<ReconnectMod>('../../../lib/reconnect.ts')
  for (const t of ['Unavailable: Network Error', '▲ Load failed  [RETRY]', 'TypeError: Failed to fetch', 'timeout of 10000ms exceeded',
    'Request failed with status code 502', 'HTTP 503', 'Scheduler: ECONNREFUSED', 'DESK FAILED TO RENDER'])
    check(`failed-load text recognised: ${t}`, R.needsReloadAfterOutage(t))
  for (const t of ['', null, 'NIFTY 22,600.00 ▲ 0.4%', 'No trades this month', 'market closed today · showing the last session',
    'Request failed with status code 404', 'data unavailable for this stock'])
    check(`healthy text left alone: ${t}`, !R.needsReloadAfterOutage(t))
  const shell = await read('../PlatformShell.tsx')
  check('PlatformShell dispatches the reconnected event on LINK DOWN → UP', /dispatchEvent\(new CustomEvent<ReconnectedDetail>\(RECONNECTED_EVENT/.test(shell))
  const page = await read('../../../app/page.tsx')
  check('page.tsx reloads a page that shows failed loads after an outage', /needsReloadAfterOutage\(page\)\) setPageEpoch\(e => e \+ 1\)/.test(page))
  const notices = await read('../ShellNotices.tsx')
  check('banner no longer promises what it cannot (round-1 copy gone)', !/the terminal resumes on its own/.test(notices))
}

async function bootstrapGateChecks(): Promise<void> {
  const page = await read('../../../app/page.tsx')
  // C1-trader-ux-03: no page waits on the 3 bootstrap calls; the 0.9 MB list loads for EQS only
  check('no blocking "Backend unreachable" gate', !/<Panel title="Backend unreachable"/.test(page) && !/pageLoading \?/.test(page))
  check('no Promise.all bootstrap of summary + enrichment + list', !/Promise\.all\(\[\s*getDashboardSummary\(\),\s*getEnrichmentStatus\(\),\s*listStocks\(0, 1500\)/.test(page))
  check('stock list only when EQS is shown', /if \(view === 'stocks' && stocksState === 'idle'\) loadStocks\(\)/.test(page))
  check('enrichment status only on OVRV', /if \(view !== 'overview' \|\| enrichAsked\.current\) return/.test(page))
  check('every page renders inside its own error boundary', /<TabErrorBoundary name=\{code\} tab=\{view\} resetKey=\{pageKey\}>\s*\{renderPage\(\)\}/.test(page))
  check('footer status follows the link state, not the first load', /linkDown \? 'OFFLINE · LINK DOWN' : 'READY'/.test(page) && !/loadError \? 'OFFLINE' : 'READY'/.test(page))
  check('PipelineStudio mounted only once visited (C2-performance-06)', /\{pipelineSeen && \(/.test(page))
  check('ErrorCatcher overlay only behind the debug flag', /if \(!enabled \|\| shown\.length === 0\) return null/.test(await read('../../ErrorCatcher.tsx')))
  const ge = await read('../../../app/global-error.tsx')
  check('global-error shows no raw stack by default (details disclosure)', /\{details && \(/.test(ge) && /reportClientError\(error/.test(ge))
  const tabs = await read('../../shell/tabModules.ts')
  check('boot preload: one loader per split page + the stock window', (tabs.match(/: \(\) => import\('@\/components\//g) ?? []).length === 43)
  const shell = await read('../PlatformShell.tsx')
  check('PlatformShell preloads the URL page during the boot gate (C2-performance-02)', /preloadTab\(first\)/.test(shell) && /BOOT_PRELOAD_MAX_MS/.test(shell))
}

async function chromeChecks(): Promise<void> {
  const header = await read('../../MarketCommandHeader.tsx')
  // C2-performance-07: no 1 s interval in the header body; the clock is a memo'd second-aligned leaf
  check('header clock is its own memo leaf on useSecondTick', /const HeaderClock = memo\(function HeaderClock\(\) \{\s*const now = useSecondTick\(\)/.test(header))
  check('no header-wide setInterval(…, 1000) clock', !/setInterval\(tick, 1000\)/.test(header))
  // C1-trader-ux-06: in the app the strip is the single brand / clock / session / lights source
  check('desktop header drops brand, clock + session and DATA/DB lights', /\{!desktop && \(\s*<div/.test(header) && /\{!desktop && <HeaderClock \/>\}/.test(header) && /\{!desktop && <>\s*<Light name="DATA"/.test(header))
  check('row 1 clips instead of widening the page (C1-trader-ux-10)', /data-sd-row1 style=\{\{ height: desktop \? 36 : 44,[\s\S]{0,200}overflow: 'hidden', whiteSpace: 'nowrap'/.test(header))
  check('UPDATE DATA asks first (C1-trader-ux-12)', /START DOWNLOAD/.test(header) && !/↻<\/span> REFRESH/.test(header))
  check('NIFTY chip via the closed / link-down aware rule (C1-trader-ux-13)', /niftySourceChip\(\{ src, wsConnected, marketOpen, linkDown/.test(header))
  const css = await read('../../../app/globals.css')
  check('NEWS pulse + NEW BUILD glow + down dot are finite (C2-performance-03)',
    /\.nd-dot-new \{ animation: nd-pulse 1\.2s ease-in-out 3; \}/.test(css) && /sd-attn 2\.4s ease-in-out 3;/.test(css)
    && /t-pulse 1\.2s ease-in-out 6;/.test(css) && !/nd-pulse[^;]*infinite/.test(css))
  check('reduced motion covers the news pulse', /prefers-reduced-motion: reduce\) \{\s*\.nd-dot-new/.test(css))
  const dock = await read('../../news/NewsDock.tsx')
  check('NewsDock: no inline endless pulse', !/infinite/.test(dock) && /className=\{isNew \? 'nd-dot-new' : undefined\}/.test(dock))
  check('NewsDock first visit with no scan starts the marker at 0 (later scan pulses)', /if \(marked\.current === false && d\) \{/.test(dock) && /Number\(d\.latest_version\) \|\| 0/.test(dock))
  const strip = await read('../TitleStrip.tsx')
  check('strip build chip says BUILD (the UI dot keeps UI)', /sd-strip-k" \{\.\.\.DRAG\}>BUILD</.test(strip))
}

async function zoomChecks(): Promise<void> {
  const Z = await load<ZoomMod>('../zoom.ts')
  eq('clampZoom', [1, 0.8, 1.25, 0.1, 9, NaN, -1, 'x', undefined].map(Z.clampZoom), [1, 0.8, 1.25, 0.5, 2, 1, 1, 1, 1])
  eq('strip height in CSS px keeps 32 screen px', [1, 0.8, 0.5, 1.25, 2].map(Z.stripHeightCss), [32, 40, 64, 25.6, 16])
  for (const z of [0.5, 0.8, 0.9, 1, 1.1, 1.5, 2]) {
    check(`strip height × zoom = 32 screen px at zoom ${z}`, Math.abs(Z.stripHeightCss(z) * z - 32) < 0.02)
  }
  // R-UI-SHELL-11: the tautological stripScreenPx (cssPx * (1 / z) * z) and its 7 "84 screen px" checks are gone
  check('no tautological stripScreenPx left (it could never fail)', !('stripScreenPx' in Z))
  check('the inset constant is still the strip CSS value', Z.STRIP_INSET_SCREEN_PX === 84)
  const strip = await read('../TitleStrip.tsx')
  check('TitleStrip counter-zooms (CSS zoom 1 / factor)', /zoom: 1 \/ z/.test(strip))
  check('TitleStrip STRIP_HEIGHT matches zoom.ts', /export const STRIP_HEIGHT = 32\b/.test(strip) && Z.STRIP_SCREEN_PX === 32)
  const css = await read('../../../app/globals.css')
  check('the 84 px inset is in the strip CSS (counter-zoomed with it)', /padding: 0 6px 0 84px;/.test(css))
  const shell = await read('../PlatformShell.tsx')
  check('PlatformShell takes zoom from the shell (event + init global, K3)', /ev\.type === 'zoom'/.test(shell) && /__SURYADHANA_ZOOM__/.test(shell) && /stripHeightCss\(zoom\)/.test(shell))
}

async function sharedFetchChecks(): Promise<void> {
  const F = await load<SharedFetchMod>('../../../lib/sharedFetch.ts')
  eq('IST date rolls at IST midnight', [F.istDate(Date.parse('2026-10-25T18:29:59Z')), F.istDate(Date.parse('2026-10-25T18:30:00Z'))], ['2026-10-25', '2026-10-26'])
  let now = Date.parse('2026-10-25T05:00:00Z')
  const c = F.createSharedCache<number>({ ttlMs: 30 * 60_000, now: () => now })
  let calls = 0
  const fetcher = () => { calls++; return Promise.resolve(calls) }
  const p1 = c.get('0:7', fetcher)
  const p2 = c.get('0:7', fetcher)
  check('header + strip + BRIEF share ONE request per page load', p1 === p2 && calls === 1)
  c.get('30:120', fetcher)
  eq('another query is its own request', calls, 2)
  now += 29 * 60_000
  c.get('0:7', fetcher)
  eq('reused within the TTL', calls, 2)
  now += 2 * 60_000
  c.get('0:7', fetcher)
  eq('refetched after the TTL', calls, 3)
  now = Date.parse('2026-10-25T18:31:00Z')               // IST date flips (00:01 on the 26th)
  c.get('0:7', fetcher)
  eq('refetched on a new IST date', calls, 4)
  let failNext = true
  const flaky = () => { calls++; return failNext ? Promise.reject(new Error('down')) : Promise.resolve(calls) }
  const before = calls
  await c.get('x', flaky).catch(() => undefined)
  failNext = false
  await c.get('x', flaky)
  eq('a failed request is not cached (next caller retries)', calls - before, 2)
  const api = await read('../../../lib/api.ts')
  check('getEcoCalendar shares only the BRIEF / session-clock query', /back === ECO_SHARED_QUERY\.back && ahead === ECO_SHARED_QUERY\.ahead \? ecoCache\.get/.test(api))
  const brief = await read('../../Brief.tsx')
  check('BRIEF still asks for that exact query (else the sharing silently stops)', /getEcoCalendar\(0, 7\)/.test(brief))
  const hol = await read('../holidays.ts')
  check('holidays use the shared query (no own fetch)', /getEcoCalendar\(ECO_SHARED_QUERY\.back, ECO_SHARED_QUERY\.ahead\)/.test(hol) && !/fetch\(/.test(hol))
}

async function holidayStoreChecks(): Promise<void> {
  const H = await load<HolidayStoreMod>('../holidayStore.ts')
  type Timer = { fn: () => void; ms: number; live: boolean }
  const timers: Timer[] = []
  let answer: 'fail' | 'ok' = 'fail'
  let fetches = 0
  const st = H.createHolidayStore({
    fetchEvents: () => { fetches++; return answer === 'ok' ? Promise.resolve([{ date: '2026-11-10', kind: 'HOLIDAY', what: 'NSE closed · Diwali' }]) : Promise.reject(new Error('down')) },
    parse: ev => new Map((ev as Array<{ date: string; what: string }>).map(e => [e.date, e.what])),
    setTimer: (fn, ms) => { const t = { fn, ms, live: true }; timers.push(t); return t },
    clearTimer: t => { (t as Timer).live = false },
    retryMs: 120_000,
  })
  const tick = () => new Promise(r => setTimeout(r, 0))
  const off = st.subscribe(() => undefined)
  st.load('2026-10-25')
  st.load('2026-10-25')
  eq('one request per date', fetches, 1)
  await tick()
  check('a failure schedules a retry', st.retryPending('2026-10-25'))
  // the round-1 gap: the old date's retry is still pending when the IST date flips and the new date's fetch fails
  st.load('2026-10-26')
  await tick()
  check("old date's retry cancelled on the date change", timers[0].live === false)
  check('the new date gets its OWN retry (round-1 leftover fixed)', st.retryPending('2026-10-26'))
  answer = 'ok'
  timers[timers.length - 1].fn()
  await tick()
  eq('retry succeeds → holidays known', [...(st.get('2026-10-26') ?? new Map()).keys()], ['2026-11-10'])
  check('no retry pending once known', !st.retryPending('2026-10-26'))
  off()
  answer = 'fail'
  st.load('2026-10-27')
  await tick()
  const t = timers[timers.length - 1]
  const n = fetches
  t.fn()
  await tick()
  eq('no listener left → the retry does not refetch', fetches, n)
}

async function feedChecks(): Promise<void> {
  const F = await load<FeedStateMod>('../../../lib/feedState.ts')
  eq('session day', [F.sessionDay('23-Oct-2026 15:30'), F.sessionDay('2026-10-23T15:30:00'), F.sessionDay('x'), F.sessionDay(null)], ['23-OCT', '23-OCT', null, null])
  const chip = (o: Partial<Parameters<FeedStateMod['niftySourceChip']>[0]>) =>
    F.niftySourceChip({ src: 'NSE', wsConnected: false, marketOpen: true, linkDown: false, asOf: '23-Oct-2026 15:30', ...o })
  eq('market open: the original chips', [chip({}).text, chip({ src: 'ICICI', wsConnected: true }).text, chip({ src: 'ICICI' }).text, chip({ src: 'STALE' }).text],
    ['● NSE', '● LIVE', '● ICICI', '◌ STALE'])
  eq('closed market: never ● NSE / ● LIVE', [chip({ marketOpen: false }).text, chip({ marketOpen: false, src: 'ICICI', wsConnected: true }).text,
    chip({ marketOpen: false, asOf: null }).text], ['CLOSE 23-OCT', 'CLOSE 23-OCT', 'CLOSED'])
  eq('link down: STALE whatever the source', [chip({ linkDown: true }).text, chip({ linkDown: true, src: 'ICICI', wsConnected: true }).tone], ['◌ STALE', 'down'])
  const sock = (o: Partial<Parameters<FeedStateMod['socketChip']>[0]>) =>
    F.socketChip({ connected: true, marketOpen: true, linkDown: false, live: '● STREAMING', offline: '◌ WS RECONNECTING', ...o }).text
  eq('socket chip', [sock({}), sock({ marketOpen: false }), sock({ linkDown: true }), sock({ connected: false })],
    ['● STREAMING', '● SOCKET OK · NO TICKS', '◌ LINK DOWN', '◌ WS RECONNECTING'])
}

// ── round 3 shell (F3-UI-SHELL) ────────────────────────────────────────────────────────────────────────────

async function specialSessionChecks(): Promise<void> {
  const S = await load<SessionMod>('../session.ts')
  // R-UI-SHELL-03 / CT-10: the Sun 8 Nov 2026 Muhurat session is never plain WEEKEND
  const mu = S.nseSession(ist('2026-11-08T18:15:00'))
  eq('8 Nov 2026 (Sunday): CLOSED · SPECIAL with the session name (timings not published)', [mu.state, mu.reason, mu.special?.label],
    ['CLOSED', 'SPECIAL', 'MUHURAT'])
  eq('header says MUHURAT (amber), not WEEKEND', [S.headerSession(mu).label, S.headerSession(mu).tone], ['MUHURAT', 'amber'])
  check('header carries the session name for its tooltip', /Muhurat/.test(S.headerSession(mu).holiday ?? ''))
  eq('negative control: without the specials list it is WEEKEND (the old behaviour)', S.nseSession(ist('2026-11-08T18:15:00'), null, null).reason, 'WEEKEND')
  // once NSE publishes the window, it is OPEN inside it and SPECIAL outside it
  const specials = { '2026-11-08': { name: 'Muhurat trading', label: 'MUHURAT' as const, from: 18 * 60, to: 19 * 60 + 15 } }
  eq('inside the published window: OPEN', [S.nseSession(ist('2026-11-08T18:30:00'), null, specials).state, S.headerSession(S.nseSession(ist('2026-11-08T18:30:00'), null, specials)).label],
    ['OPEN', 'NSE OPEN'])
  eq('before / after the window: CLOSED · SPECIAL', ['17:59:00', '19:15:00'].map(t => S.nseSession(ist(`2026-11-08T${t}`), null, specials).reason), ['SPECIAL', 'SPECIAL'])
  eq('ordinary days are unchanged', [S.nseSession(ist('2026-11-07T11:00:00')).reason, S.nseSession(ist('2026-11-09T10:00:00')).state], ['WEEKEND', 'OPEN'])
  check('an ordinary day has no special', S.nseSession(ist('2026-11-09T10:00:00')).special === null)
  // drift: every NSE special session date is also in shared/mcx_specs.py SPECIAL_SESSIONS_2026
  const py = await read('../../../../shared/mcx_specs.py')
  const dates = [...py.matchAll(/"date":\s*"(\d{4}-\d{2}-\d{2})"/g)].map(m => m[1])
  check('special sessions match shared/mcx_specs.py', Object.keys(S.SPECIAL_SESSIONS).every(d => dates.includes(d)) && dates.length > 0, dates.join(','))
  const strip = await read('../TitleStrip.tsx')
  check('the strip shows SPECIAL + the session name', /s\.reason === 'SPECIAL' \? 'SPECIAL' : s\.state/.test(strip) && /sessionDetail/.test(strip) && /s\.special/.test(strip))
}

async function liveFeedChecks(): Promise<void> {
  const F = await load<FeedStateMod>('../../../lib/feedState.ts')
  eq('NSE stamp → epoch (IST)', [F.nseTimeToEpoch('23-Oct-2026 15:30'), F.nseTimeToEpoch('08-Nov-2026 18:05:30'), F.nseTimeToEpoch('x'), F.nseTimeToEpoch(null)],
    [Date.parse('2026-10-23T10:00:00Z'), Date.parse('2026-11-08T12:35:30Z'), null, null])
  const muhurat = ist('2026-11-08T18:20:00')
  check('a print 2 min old is fresh', F.isFreshPrint('08-Nov-2026 18:18', muhurat))
  check("Friday's close on Sunday is not fresh", !F.isFreshPrint('06-Nov-2026 15:30', muhurat))
  check('a stamp far in the future is not fresh', !F.isFreshPrint('08-Nov-2026 19:30', muhurat))
  eq('tick age rule', [F.isLiveTick(muhurat - 30_000, muhurat), F.isLiveTick(muhurat - 91_000, muhurat), F.isLiveTick(0, muhurat)], [true, false, false])
  // the header chip during Muhurat: the calendar says closed, NSE prints → ● NSE (was CLOSE 06-NOV)
  const chip = (o: Partial<Parameters<FeedStateMod['niftySourceChip']>[0]>) =>
    F.niftySourceChip({ src: 'NSE', wsConnected: false, marketOpen: false, linkDown: false, asOf: '08-Nov-2026 18:18', now: muhurat, ...o })
  eq('Muhurat: a fresh NSE print beats the calendar', chip({}).text, '● NSE')
  eq('Muhurat: an ICICI tick (marketOpen via useFeedState) reads LIVE', chip({ src: 'ICICI', wsConnected: true, marketOpen: true }).text, '● LIVE')
  eq('weekend, stale print: still CLOSE <day>', chip({ asOf: '06-Nov-2026 15:30' }).text, 'CLOSE 06-NOV')
  eq('negative control: without `now` the calendar alone decides (the round-2 behaviour)', chip({ now: undefined }).text, 'CLOSE 08-NOV')
  eq('link down still wins', chip({ linkDown: true }).text, '◌ STALE')
  // R-UI-SHELL-06 / C-PERF-06: chrome polling slows only while closed or hidden
  eq('poll cadence', [F.chromePollMs(5000, { marketOpen: true, hidden: false }), F.chromePollMs(5000, { marketOpen: false, hidden: false }),
    F.chromePollMs(15_000, { marketOpen: true, hidden: true }), F.chromePollMs(60_000, { marketOpen: true, hidden: true }, 300_000),
    F.chromePollMs(60_000, { marketOpen: true, hidden: false }, 300_000)], [5000, 60_000, 60_000, 300_000, 60_000])
  // the evidence store: listeners hear the edge into "ticking" only, not every tick
  const L = await load<LiveEvidenceMod>('../../../lib/liveEvidence.ts')
  L.resetLiveEvidence()
  let edges = 0
  const off = L.subscribeLiveEvidence(() => { edges++ })
  L.noteLiveTick(1_000_000); L.noteLiveTick(1_001_000); L.noteLiveTick(1_002_000)
  eq('evidence: one edge for a burst of ticks', [edges, L.lastLiveTickAt()], [1, 1_002_000])
  L.noteLiveTick(1_002_000 + F.LIVE_TICK_MAX_AGE_MS + 1)
  eq('evidence: a new edge after a quiet spell', edges, 2)
  L.noteNsePrint('23-Oct-2026 15:30'); L.noteNsePrint(''); L.noteNsePrint(null)
  eq('evidence: last NSE stamp kept (blank ignored)', L.lastNsePrint(), '23-Oct-2026 15:30')
  off()
  L.resetLiveEvidence()
  const ctx = await read('../../../context/AppContext.tsx')
  check('AppContext hands every socket message to noteQuoteMessage (never a bare noteLiveTick per message, round 4b)',
    /noteQuoteMessage\(data\)/.test(ctx) && !/noteLiveTick\(\)/.test(ctx))
  check('data-service status poll: 30 s visible, 2 min hidden (C-PERF-06)', /usePolling\(refreshDataStatus, hidden \? 120_000 : 30_000\)/.test(ctx)
    && !/setInterval\(refreshDataStatus, 30_000\)/.test(ctx))
  const dock = await read('../../news/NewsDock.tsx')
  check('news dock poll: 60 s visible, 5 min hidden (C-PERF-06)', /usePolling\(poll, useDocumentHidden\(\) \? 300_000 : 60_000\)/.test(dock)
    && !/setInterval\(poll, 60_000\)/.test(dock))
  const feed = await read('../../shell/useFeed.ts')
  check('useFeedState: marketOpen = calendar OR live ticks', /marketOpen: calendarOpen \|\| ticking/.test(feed))
  const header = await read('../../MarketCommandHeader.tsx')
  check('header NIFTY chip passes `now` (fresh NSE print beats the calendar) and the quote time (P9 STALE)',
    /niftySourceChip\(\{ src, wsConnected, marketOpen, linkDown, asOf: nse\?\.time \?\? null, now: Date\.now\(\), quoteAt \}\)/.test(header))
  check('header NIFTY polls go through chromePollMs (60 s closed / hidden)', /chromePollMs\(15_000, \{ marketOpen: printing, hidden \}\)/.test(header)
    && /chromePollMs\(5000, \{ marketOpen: printing, hidden \}\)/.test(header) && !/setInterval\(poll, 5000\)/.test(header) && !/setInterval\(poll, 15_000\)/.test(header))
  check('macro tape keeps 60 s while visible, 5 min hidden', /chromePollMs\(60_000, \{ marketOpen: true, hidden \}, 300_000\)/.test(header))
  check('macro tape is marked STALE while the link is down (CT-15)', /linkDown\s*\n?\s*\? <span[^>]*>◌ STALE/.test(header) && /opacity: linkDown \? 0\.55 : 1/.test(header))
  check('the header notes the NSE stamp for the stock window', /noteNsePrint\(j\?\.time\)/.test(header))
}

async function goAliasChecks(): Promise<void> {
  const A = await load<GoAliasesMod>('../../../lib/goAliases.ts')
  const k = (q: string) => A.aliasTargets(q).map(t => (t.kind === 'page' ? `page:${t.id}` : t.kind === 'omon' ? `omon:${t.sym}` : t.kind))
  eq('mnemonics', ['GP', 'gip', 'TOP', 'N', 'MOST', 'BACK', 'BRIEF', 'NIFTY', 'banknifty'].map(q => k(q).join(',')),
    ['page:charts', 'page:charts', 'news', 'news', 'page:movers', 'back', 'page:brief', 'omon:NIFTY,page:memb', 'omon:BANKNIFTY,page:memb'])
  eq('not a mnemonic: tickers, partial words, two words', ['TCS', 'GPI', 'TCS GP', '', 'BACKTEST'].map(q => k(q).length), [0, 0, 0, 0, 0])
  eq('Back only while the entry behind is a terminal screen', [A.canGoBack({ sd: 1, tab: 'desk', sym: null, pushed: true }),
    A.canGoBack({ sd: 1, tab: 'brief', sym: null, pushed: false }), A.canGoBack(null), A.canGoBack({ pushed: true })], [true, false, false, false])
  eq('ranked merge keeps the first of each key', A.mergeRanked([[{ key: 'p:charts' }], [{ key: 'x' }, { key: 'p:charts' }], [{ key: 'y' }]]).map(i => i.key),
    ['p:charts', 'x', 'y'])
  // every alias page id is a real page
  const P = await load<PagesMod>('../pages.ts')
  check('alias targets are real page ids', Object.values(A.GO_ALIASES).flat().every(t => t.kind !== 'page' || t.id in P.PAGE_META))
  const bar = await read('../../CommandBar.tsx')
  check('GO ranks mnemonics and exact page codes above every ticker match (CT-09)',
    /mergeRanked\(\[aliases, exactPages, tickerLead, scoredPages, tickerRest\]\)/.test(bar) && /exactPages = pg\.filter\(i => i\.code === raw\)/.test(bar))
  check('BACK <GO> goes back only inside the terminal', /if \(it\.kind === 'back'\) \{ if \(canGoBack\(window\.history\.state\)\) window\.history\.back\(\); return \}/.test(bar))
  check('symbols rows go through sanitizeSymbolRows (R-UI-SHELL-04 / P15 crash)', /setSymbols\(sanitizeSymbolRows<SymbolEntry>\(r\.data\?\.data\)\)/.test(bar)
    && /label: s\?\.n \|\| t,/.test(bar))
  const K = await load<ShortcutsMod>('../../../lib/shortcuts.ts')
  check('help teaches the mnemonics', K.helpKeys(true).some(([key]) => /GP · TOP · MOST · BACK/.test(key)))
}

async function macKeyChecks(): Promise<void> {
  const K = await load<ShortcutsMod>('../../../lib/shortcuts.ts')
  // R-UI-SHELL-08: a browser on macOS goes Back / Forward with ⌘[ / ⌘], not Alt+← / Alt+→
  eq('isMacPlatform', [K.isMacPlatform({ platform: 'MacIntel' }), K.isMacPlatform({ userAgentData: { platform: 'macOS' } }), K.isMacPlatform({ platform: 'Win32' }),
    K.isMacPlatform({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' }), K.isMacPlatform({ platform: 'Linux x86_64' }), K.isMacPlatform(null)],
    [true, true, false, true, false, false])
  const macWeb = K.helpKeys(false, true).map(r => r[0]).join(' | ')
  check('browser on a Mac: help says ⌘[ · ⌘]', /⌘ \[/.test(macWeb) && !/Alt ←/.test(macWeb), macWeb)
  check('browser elsewhere: help keeps Alt ← · Alt →', /Alt ←/.test(K.helpKeys(false, false).map(r => r[0]).join(' | ')))
  check('footer on a Mac browser', /⌘\[ ⌘\] BACK\/FWD/.test(K.footerHint(false, true)) && !/ALT\+←/.test(K.footerHint(false, true)))
  check('footer elsewhere unchanged', K.footerHint(false) === 'ALT+1…0 PAGES · ALT+←/→ BACK/FWD · SHIFT+N NEWS · ? HELP · ESC CLOSE')
  const page = await read('../../../app/page.tsx')
  check('page.tsx passes the Mac flag to the footer', /footerHint\(desktop, mac\)/.test(page))
}

async function outageChecks(): Promise<void> {
  const R = await load<ReconnectMod>('../../../lib/reconnect.ts')
  // R-UI-SHELL-05: the in-page notice and the banners are healthy text (a future wording must not remount every page)
  const notices = await read('../ShellNotices.tsx')
  const bannerDown = /BANNER_DOWN_DETAIL = '([^']+)'/.exec(notices)?.[1] ?? ''
  const bannerUp = /BANNER_UP_DETAIL = '([^']+)'/.exec(notices)?.[1] ?? ''
  const page = await read('../../../app/page.tsx')
  const linkDown = /<b>LINK DOWN<\/b>\s*<span>\{downAt \? `since \$\{downAt\} IST · ` : ''\}([\s\S]*?)<\/span>/.exec(page)?.[1].replace(/\s+/g, ' ').trim() ?? ''
  check('LINK DOWN notice text found', linkDown.length > 20, linkDown)
  for (const t of [linkDown, `LINK DOWN since 14:40:00 IST · ${linkDown}`, bannerDown, bannerUp, 'ui-api unreachable · reconnecting'])
    check(`notice / banner text never triggers a reload: ${t.slice(0, 50)}`, !R.needsReloadAfterOutage(t), t)
  // and the scan never sees them anyway: only the page content is scanned
  check('only the active .sd-page is scanned (never main / the notice)', /querySelector<HTMLElement>\(`\.sd-page\[data-page="\$\{viewRef\.current\}"\]`\)/.test(page)
    && !/mainRef\.current\?\.innerText/.test(page))
  check('page and stock window have separate reload epochs', /if \(needsReloadAfterOutage\(page\)\) setPageEpoch\(e => e \+ 1\)/.test(page)
    && /if \(needsReloadAfterOutage\(stock\)\) setStockEpoch\(e => e \+ 1\)/.test(page) && /key=\{`stock:\$\{stockEpoch\}`\}/.test(page)
    && /const pageKey = `\$\{view\}:\$\{pageEpoch\}`/.test(page))
  check('each window waits a random 0–2 s before reloading', /\}, reconnectDelayMs\(\)\)/.test(page))
  eq('jitter bounds', [R.reconnectDelayMs(() => 0), R.reconnectDelayMs(() => 0.5), R.reconnectDelayMs(() => 0.9999999), R.reconnectDelayMs(() => NaN),
    R.reconnectDelayMs(() => 7)], [0, 1000, R.RECONNECT_JITTER_MS - 1, 0, R.RECONNECT_JITTER_MS - 1])
  let lo = Infinity, hi = -Infinity
  for (let i = 0; i < 2000; i++) { const d = R.reconnectDelayMs(); lo = Math.min(lo, d); hi = Math.max(hi, d) }
  check('jitter spreads over [0, 2 s)', lo >= 0 && hi < R.RECONNECT_JITTER_MS && hi - lo > 1000, `${lo}..${hi}`)
  // R-UI-SHELL-01: no filter / opacity on an ancestor of page content; the shade sits above the page instead
  const css = await read('../../../app/globals.css')
  check('LINK DOWN no longer filters / fades .sd-page (fixed overlays stay viewport-anchored)',
    !/\.sd-main\[data-link="down"\] \.sd-page \{[^}]*(filter|opacity)/.test(css))
  check('LINK DOWN shade: a non-interactive ::after above the page content', /\.sd-main\[data-link="down"\] \.sd-page::after \{[^}]*pointer-events: none/.test(css)
    && /\.sd-page \{ position: relative; \}/.test(css))
  // CT-15: the settings notice is in the flow, not floating over data
  check('settings notice is docked in the flow (no position: fixed)', /\.sd-note \{\s*position: relative;/.test(css) && !/\.sd-note \{[^}]*position: fixed/.test(css))
  const tb = await read('../../shell/TabErrorBoundary.tsx')
  check("the boundary's post-outage retry is jittered too", /\}, reconnectDelayMs\(\)\)/.test(tb))
}

async function boundaryChecks(): Promise<void> {
  const tb = await read('../../shell/TabErrorBoundary.tsx')
  // R-UI-SHELL-04: silent boundaries retry on page switch and on the user's next attempt
  check('boundary: retryOn / replay / cue / onFailedChange', /retryOn\?: readonly string\[\]/.test(tb) && /replay\?: \(e: Event\) => Event \| null/.test(tb)
    && /cue\?: string/.test(tb) && /onFailedChange\?\.\(true\)/.test(tb) && /onFailedChange\?\.\(false\)/.test(tb))
  check('boundary: a replayed event cannot loop (ignored while replaying)', /if \(!this\.state\.error \|\| this\.state\.chunk \|\| this\.replaying\) return/.test(tb))
  const page = await read('../../../app/page.tsx')
  check('GO boundary retries on its open command + next key and replays the command',
    /<TabErrorBoundary name="GO" variant="silent" resetKey=\{chromeKey\} retryOn=\{GO_RETRY_EVENTS\} replay=\{goReplay\}/.test(page)
    && /GO_RETRY_EVENTS = \[GO_COMMAND_EVENT, 'keydown'\] as const/.test(page))
  const K = await load<ShortcutsMod>('../../../lib/shortcuts.ts')
  const kf = (k: string, o: Record<string, unknown> = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, defaultPrevented: false, ...o })
  const free = { typing: false, blocked: false }
  eq('GO after a retry: ⌘K, /, the open command and a ticker letter open it (the letter seeds it)',
    [K.goOpenAfterRetry(kf('k', { metaKey: true }), free), K.goOpenAfterRetry(kf('/'), free), K.goOpenAfterRetry({ ...kf(''), type: K.GO_COMMAND_EVENT }, free),
     K.goOpenAfterRetry(kf('t'), free)], [{ seed: null }, { seed: null }, { seed: null }, { seed: 'T' }])
  eq('GO after a retry: other keys, typing in a field, another dialog → nothing',
    [K.goOpenAfterRetry(kf('Escape'), free), K.goOpenAfterRetry(kf('t'), { typing: true, blocked: false }), K.goOpenAfterRetry(kf('t'), { typing: false, blocked: true }),
     K.goOpenAfterRetry(kf('j', { defaultPrevented: true }), free)], [null, null, null, null])
  const barSrc = await read('../../CommandBar.tsx')
  check('CommandBar keeps only string recents (a corrupt value cannot crash the GO list)',
    /return Array\.isArray\(v\) \? v\.filter\(\(x\): x is string => typeof x === 'string' && x !== ''\)\.slice\(0, 8\) : \[\]/.test(barSrc))
  check('CommandBar opens seeded from the command event detail', /const onCommand = \(e: Event\) => show\(\(e as CustomEvent<unknown>\)\.detail\)/.test(barSrc))
  check('silent boundaries reset on a page switch (key = epoch + view)', /const chromeKey = `\$\{pageEpoch\}:\$\{view\}`/.test(page)
    && /name="WATCHLIST BAR" variant="silent" resetKey=\{chromeKey\}/.test(page) && /name="NEWS" variant="silent" cue="NEWS" resetKey=\{chromeKey\}/.test(page))
  check('the status line says when GO is unavailable', /goFailed \? '◌ GO UNAVAILABLE · RETRY' : '\/ GO'/.test(page))
  // R-UI-SHELL-09: honest report wording
  check('panel no longer claims "The error was logged for diagnosis"', !/The error was logged for diagnosis/.test(tb) && /deliveryText\(this\.state\.report\)/.test(tb))
  const ge = await read('../../../app/global-error.tsx')
  check('global card no longer claims the error was logged', !/error was logged for diagnosis/.test(ge) && /deliveryText\(report\)/.test(ge))
  const chip = await read('../../ErrorCatcher.tsx')
  check("error chip: 'IN THIS WINDOW' and a per-entry delivery label", /UI ERRORS IN THIS WINDOW/.test(chip) && !/ON THIS PAGE/.test(chip) && /DELIVERY_LABEL\[e\.delivery\]/.test(chip))
  const E = await load<ClientErrorsMod>('../../../lib/clientErrors.ts')
  eq('delivery wording', [E.deliveryText({ delivery: 'reported' }), E.deliveryText({ delivery: 'failed' }), E.deliveryText({ delivery: 'not-sent' }),
    E.deliveryText({ delivery: 'sending' }), E.deliveryText(null)].map(t => t.split(' ').slice(0, 4).join(' ')),
    ['It was reported to', 'It could not be', 'It was not reported', 'Reporting it to ui-api…', 'It was not reported'])
  // delivery outcome with a fake window: 204 → reported, 503 → failed, network error → failed, readonly → not-sent
  const g4 = globalThis as unknown as { window?: unknown; fetch?: unknown }
  const prev = [g4.window, g4.fetch]
  const store = new Map<string, string>()
  g4.window = Object.assign(new EventTarget(), {
    location: { href: 'http://127.0.0.1:8010/?tab=desk', search: '?tab=desk', protocol: 'http:' },
    localStorage: { getItem: (k: string) => store.get(k) ?? null },
  })
  try {
    const tick = () => new Promise(r => setTimeout(r, 0))
    g4.fetch = (() => Promise.resolve(new Response(null, { status: 204 }))) as typeof fetch
    const a = E.reportClientError(new Error('r3 ok'), { kind: 'render' })
    eq('delivery: sending while the POST is in flight', a?.delivery, 'sending')
    await tick(); await tick()
    eq('delivery: 2xx → reported', a?.delivery, 'reported')
    g4.fetch = (() => Promise.resolve(new Response('{}', { status: 503 }))) as typeof fetch
    const b = E.reportClientError(new Error('r3 5xx'), { kind: 'render' })
    await tick(); await tick()
    eq('delivery: 5xx → failed (never "reported")', b?.delivery, 'failed')
    g4.fetch = (() => Promise.reject(new TypeError('Load failed'))) as typeof fetch
    const c = E.reportClientError(new Error('r3 down'), { kind: 'render' })
    await tick(); await tick()
    eq('delivery: ui-api unreachable → failed', c?.delivery, 'failed')
    store.set(E.QA_MODE_KEY, 'readonly')
    const d = E.reportClientError(new Error('r3 qa'), { kind: 'render' })
    eq('delivery: readonly QA → not-sent', [d?.delivery, d?.sent], ['not-sent', false])
    E.clearClientErrors()
  } finally {
    [g4.window, g4.fetch] = prev
  }
}

async function shellUxChecks(): Promise<void> {
  const header = await read('../../MarketCommandHeader.tsx')
  // R-UI-SHELL-12 / CT-04: focus starts on CANCEL; inside the EOD window START needs a second click
  check('UPDATE DATA confirm autofocuses CANCEL, not START', /<button autoFocus onClick=\{\(\) => setAsk\(false\)\}/.test(header)
    && !/<button autoFocus onClick=\{\(\) => \{ setAsk\(false\); onConfirm\(\) \}\}/.test(header))
  check('inside the EOD window START needs a second click', /if \(eod && !armed\) \{ setArmed\(true\); return \}/.test(header))
  const page = await read('../../../app/page.tsx')
  check("a failed UPDATE DATA request says UPDATE FAILED (never 'Refresh complete')", /setTriggerError\(apiError\(err, 'the update request failed'\)\)/.test(page)
    && /`UPDATE FAILED · \$\{p\.triggerError\}`/.test(page) && !/'Refresh complete'/.test(page))
  check('a failed progress poll says PROGRESS UNAVAILABLE', /setStatusError\(apiError\(err, 'progress unavailable'\)\)/.test(page) && /PROGRESS UNAVAILABLE/.test(page))
  check('the setup commands sit behind a disclosure; no yfinance / 5yr OHLCV dev copy', /<summary[^>]*>manual setup \(terminal\)<\/summary>/.test(page)
    && !/via yfinance/.test(page) && !/\.NS suffix/.test(page))
  check('no infinite pulse on the per-ticker badges', !/animate-pulse/.test(page))
  // R-UI-SHELL-02: OVRV shows — / LOADING until the summary arrives, and only the error after a failure
  check('OVRV: no invented zeros before the summary', /const num = \(n: number\) => \(loaded \? n\.toLocaleString\('en-IN'\) : '—'\)/.test(page)
    && /<Chip color=\{T\.muted\}>LOADING<\/Chip>/.test(page) && /disabled=\{enriching \|\| !loaded\}/.test(page))
  check('OVRV: after a failure only the error (no zero grid)', /\{\(loaded \|\| !dashError\) && \(\s*<Grid cols=\{5\}>/.test(page))
  // C1-trader-ux-16 remainder: ⌘-click / middle-click on a TickerLink opens a new window on this page
  const kit = await read('../../terminal/index.tsx')
  const tl = /export function TickerLink[\s\S]*?\n\}\n/.exec(kit)?.[0] ?? ''
  check('TickerLink: ⌘/Ctrl-click and middle-click → newWindow(tab, sym)', /if \(e\.metaKey \|\| e\.ctrlKey\) \{ openInNewWindow\(e\); return \}/.test(tl)
    && /onMouseUp=\{e => \{ if \(e\.button === 1\) openInNewWindow\(e\) \}\}/.test(tl) && !/onAuxClick=/.test(tl)
    && /if \(e\.button !== 0\) return/.test(tl) && /void newWindow\(tab, /.test(tl))
  // C2-performance-03 remainder / CT-07: the stock window's price line
  const modal = await read('../../StockDetailModal.tsx')
  check('stock window: no endless pulse on the price or intraday dot', !/rounded-full bg-emerald-400 animate-pulse/.test(modal))
  check('stock window: price line with change, % and the shared CLOSE / DELAYED / LIVE rule (stockPriceMarker)', /function priceLine\(/.test(modal)
    && /const marker = stockPriceMarker\(\{ live: i\.live, marketOpen: i\.marketOpen, asOf: i\.asOf, nseStamp: i\.nseStamp, now: Date\.now\(\) \}\)/.test(modal)
    && /data-sd-price=\{px\.marker\}/.test(modal)
    // live program (reports/live_nse, D4): the live NSE quote service's row is the only price (its own state → the marker,
    // liveMarker); the legacy branch keeps the REST quote's time; the old 2 s /api/quotes/ticks overlay (Yahoo when ticks
    // were off) is gone from the window
    && /live: false, marketOpen, asOf: quoteAt, nseStamp: lastNsePrint\(\)/.test(modal) && /marker: liveMarker\(lqInfo, lq\.ltt\)/.test(modal)
    && !/useLiveTicks\(/.test(modal))
  check('stock window: the REST quote\'s own previous close is the last change base (change and % shown with only that quote)',
    /impliedPrev\(liveQ\?\.ltp, liveQ\?\.change_pct\)\s*\n\s*\?\? quotePrev,/.test(modal) && /setQuotePrev\(Number\.isFinite\(pc\) && pc > 0 \? pc : null\)/.test(modal))
  check('stock window header wraps instead of overlapping ☆ PIN', /flex flex-wrap justify-between items-center gap-x-4 gap-y-2 z-10/.test(modal))
  check('stock window shows the company name', /\[detail\?\.company_name, detail\?\.fundamentals\?\.sector\]\.filter\(Boolean\)\.join\(' · '\)/.test(modal))
  // SECREL-01 wiring (the behaviour test is ui/lib/__tests__/streamProxy.check.ts, with the real guard)
  for (const f of ['ml/train/stream', 'analytics/backtest/stream', 'analytics/wfo-backtest/stream', 'telemetry/logs/stream',
    'pipeline/ml-stream/[job_id]', 'pipeline/rl-stream/[job_id]']) {
    const src = await read(`../../../app/api/${f}/route.ts`)
    check(`route ${f} forwards the browser context (streamProxyHeaders)`, /headers: streamProxyHeaders\(req\.headers, /.test(src) && /import type \{ NextRequest \}/.test(src))
  }
}


// ── round 4b shell (F4B-UI-SHELL) ───────────────────────────────────────────────────────────────────────────

/** The round-3 rule, kept here as the negative control: every socket message with a symbol was a live tick. */
function round3Rule(msgs: unknown[]): boolean {
  return msgs.some(m => !!m && typeof m === 'object' && !!((m as { symbol?: unknown }).symbol || (m as { payload?: { symbol?: unknown } }).payload?.symbol))
}

async function liveEvidenceChecks(): Promise<void> {
  const F = await load<FeedStateMod>('../../../lib/feedState.ts')
  const L = await load<LiveEvidenceMod>('../../../lib/liveEvidence.ts')
  // exchange stamps: NSE/Breeze REST, Breeze websocket, ISO with a zone; never a bare number or a zone-less ISO
  eq('exchange time formats', [F.exchangeTimeToEpoch('23-Oct-2026 15:35:52'), F.exchangeTimeToEpoch('Fri Oct 23 15:35:52 2026'),
    F.exchangeTimeToEpoch('Oct 23 15:35:52 2026'), F.exchangeTimeToEpoch('2026-10-23T15:35:52+05:30'), F.exchangeTimeToEpoch('2026-10-23T10:05:52Z')],
    [Date.parse('2026-10-23T10:05:52Z'), Date.parse('2026-10-23T10:05:52Z'), Date.parse('2026-10-23T10:05:52Z'), Date.parse('2026-10-23T10:05:52Z'),
     Date.parse('2026-10-23T10:05:52Z')])
  eq('not exchange times', [F.exchangeTimeToEpoch(1761213952), F.exchangeTimeToEpoch('2026-10-23T15:35:52'), F.exchangeTimeToEpoch(''),
    F.exchangeTimeToEpoch(null), F.exchangeTimeToEpoch('Xyz Oct 99 1:2:3 2026')], [null, null, null, null, null])
  // what is a quote at all
  const q = (sym: string, ltp: unknown, ltt: string | null, extra: Record<string, unknown> = {}) =>
    ({ symbol: sym, ts: 1761213952.1, payload: { ltp, ...(ltt ? { ltt } : {}), ...extra } })
  eq('heartbeat / ack / error / junk are not quotes', [F.quotePrint({ pong: true }), F.quotePrint({ ok: true, subscribed: ['TCS'] }),
    F.quotePrint({ error: 'redis_unavailable', detail: 'x' }), F.quotePrint({ error: 'bad_message' }), F.quotePrint(null), F.quotePrint('tick'),
    F.quotePrint([1]), F.quotePrint({ symbol: 'TCS' }), F.quotePrint(q('TCS', null, '23-Oct-2026 15:29:58')), F.quotePrint(q('', 1, null))],
    [null, null, null, null, null, null, null, null, null, null])
  eq('a Breeze quote message', F.quotePrint(q('nifty', 22600, '23-Oct-2026 15:35:52', { total_quantity_traded: '0' })),
    { sym: 'NIFTY', key: '22600|0', at: Date.parse('2026-10-23T10:05:52Z') })
  // the rule, message by message
  const live = ist('2026-10-26T11:00:00')
  const fresh = F.quotePrint(q('TCS', 3001, '26-Oct-2026 10:59:58'))!
  check('first message of a symbol only seeds the comparison', !F.isLivePrint(fresh, undefined, live))
  check('a new print with a fresh exchange time is live', F.isLivePrint(fresh, '3000|', live))
  check('the same print again is not (no trade)', !F.isLivePrint(fresh, '3001|', live))
  check('a stale replay is not (exchange time 2 min old)', !F.isLivePrint(F.quotePrint(q('TCS', 3002, '26-Oct-2026 10:58:00'))!, '3001|', live))
  check('no exchange time → never live (data-service ts is its publish time)', !F.isLivePrint(F.quotePrint(q('TCS', 3003, null))!, '3001|', live))
  check('a stamp far in the future is not live', !F.isLivePrint(F.quotePrint(q('TCS', 3004, '26-Oct-2026 11:05:00'))!, '3001|', live))
  // scenario A: weekday NSE holiday (Tue 10 Nov 2026), ICICI logged in: data-service publishes the previous
  // session's quotes every 15 s, the socket also answers pings and subscriptions → never ticking, chips stay closed
  L.resetLiveEvidence()
  const hol = ist('2026-11-10T11:00:00')
  const holidayStream: unknown[] = []
  for (let i = 0; i < 40; i++) {
    holidayStream.push(q('NIFTY', 24010.5, '09-Nov-2026 15:30:00'), q('TCS', 3001, '09-Nov-2026 15:29:59', { total_quantity_traded: 1200345 }),
      { pong: true }, { ok: true, subscribed: ['NIFTY', 'TCS'] })
  }
  let noted = 0
  holidayStream.forEach((m, i) => { if (L.noteQuoteMessage(m, hol + i * 3750)) noted++ })
  const holEnd = hol + holidayStream.length * 3750
  eq('holiday: no message counts as a live tick', [noted, L.lastLiveTickAt()], [0, 0])
  const holidayOpen = false || F.isLiveTick(L.lastLiveTickAt(), holEnd)          // useFeedState: calendar (holiday) || ticking
  eq('holiday: chips stay closed (CLOSE 09-NOV / SOCKET OK · NO TICKS)', [
    F.niftySourceChip({ src: 'ICICI', wsConnected: true, marketOpen: holidayOpen, linkDown: false, asOf: '09-Nov-2026 15:30', now: holEnd }).text,
    F.socketChip({ connected: true, marketOpen: holidayOpen, linkDown: false, live: '● STREAMING', offline: '◌ WS' }).text], ['CLOSE 09-NOV', '● SOCKET OK · NO TICKS'])
  check('negative control: the round-3 rule calls the same holiday stream live', round3Rule(holidayStream))
  // scenario A2: the index stamped with the fetch time (Breeze NIFTY ltt = now) but an unchanged price → still not live
  L.resetLiveEvidence()
  let idx = 0
  for (let i = 0; i < 20; i++) { const t = hol + i * 15_000; const stamp = `10-Nov-2026 ${F.istHhmm(t)}:00`; if (L.noteQuoteMessage(q('NIFTY', 24010.5, stamp), t)) idx++ }
  eq('holiday, index stamped "now" but the price never moves: not live', idx, 0)
  // scenario B: a heartbeat-only stream on a closed market (Sunday): acks and pongs only
  L.resetLiveEvidence()
  const sun = ist('2026-10-25T21:00:00')
  const beats = Array.from({ length: 30 }, (_, i) => (i % 2 ? { pong: true } : { ok: true, subscribed: ['TCS'] }))
  beats.forEach((m, i) => L.noteQuoteMessage(m, sun + i * 25_000))
  eq('heartbeat-only stream: never ticking', [L.lastLiveTickAt(), F.isLiveTick(L.lastLiveTickAt(), sun + 750_000)], [0, false])
  // scenario C: a trading session the calendar does not know, with real prints: live after the second print
  L.resetLiveEvidence()
  let edges = 0
  const off = L.subscribeLiveEvidence(() => { edges++ })
  const spec = ist('2026-11-08T18:20:00')
  const r1 = L.noteQuoteMessage(q('NIFTY', 24100.1, '08-Nov-2026 18:19:58'), spec)
  const r2 = L.noteQuoteMessage(q('NIFTY', 24102.3, '08-Nov-2026 18:20:12'), spec + 15_000)
  const r3 = L.noteQuoteMessage(q('NIFTY', 24104.0, '08-Nov-2026 18:20:27'), spec + 30_000)
  eq('special session: first print seeds, the next ones are live (one edge)', [r1, r2, r3, edges, L.lastLiveTickAt()], [false, true, true, 1, spec + 30_000])
  check('special session: socket chip streams', F.socketChip({ connected: true, marketOpen: F.isLiveTick(L.lastLiveTickAt(), spec + 40_000), linkDown: false,
    live: '● STREAMING', offline: '◌ WS' }).text === '● STREAMING')
  off()
  L.resetLiveEvidence()
}

async function priceMarkerChecks(): Promise<void> {
  const F = await load<FeedStateMod>('../../../lib/feedState.ts')
  // CT-07: the stock window honours a fresh NSE print like the header chip does
  const mu = ist('2026-11-08T18:20:00')
  const m = (o: Partial<Parameters<FeedStateMod['stockPriceMarker']>[0]>) =>
    F.stockPriceMarker({ live: false, marketOpen: false, asOf: null, nseStamp: '08-Nov-2026 18:19', now: mu, ...o })
  eq('Muhurat: a fresh NSE print → DELAYED, not CLOSE 08-NOV', m({}), 'DELAYED')
  eq('Muhurat: broker ticks → LIVE', m({ live: true }), 'LIVE')
  eq('Muhurat: the quote time is shown (ICICI ltt, ISO tick)', [m({ asOf: '08-Nov-2026 18:19:41' }), m({ asOf: '2026-11-08T18:19:41+05:30' })],
    ['DELAYED · 18:19 IST', 'DELAYED · 18:19 IST'])
  eq('a stale NSE print on a weekend: CLOSE <day>', m({ nseStamp: '06-Nov-2026 15:30' }), 'CLOSE 06-NOV')
  eq('no stamp at all on a closed market: CLOSED', m({ nseStamp: null }), 'CLOSED')
  const neg = (i: { marketOpen: boolean; nseStamp: string }) => (!i.marketOpen ? `CLOSE ${F.sessionDay(i.nseStamp)}` : 'DELAYED')
  check('negative control: the round-3 marker said CLOSE 08-NOV during Muhurat', neg({ marketOpen: false, nseStamp: '08-Nov-2026 18:19' }) === 'CLOSE 08-NOV')
  const mon = ist('2026-10-26T10:30:00')
  eq('open market: an earlier day carries its date', F.stockPriceMarker({ live: false, marketOpen: true, asOf: '23-Oct-2026 15:29:58', nseStamp: null, now: mon }),
    'DELAYED · 23-OCT 15:29 IST')
  eq('open market, unparseable as-of: DELAYED', F.stockPriceMarker({ live: false, marketOpen: true, asOf: 'yesterday', nseStamp: null, now: mon }), 'DELAYED')
}

async function staleQuoteChecks(): Promise<void> {
  const F = await load<FeedStateMod>('../../../lib/feedState.ts')
  // P9: in market hours an old quote reads STALE, never ● NSE / ● LIVE
  const t = ist('2026-10-26T11:00:00')
  const chip = (o: Partial<Parameters<FeedStateMod['niftySourceChip']>[0]>) =>
    F.niftySourceChip({ src: 'NSE', wsConnected: true, marketOpen: true, linkDown: false, asOf: '26-Oct-2026 10:59', now: t,
      quoteAt: F.nseTimeToEpoch('26-Oct-2026 10:59'), ...o })
  eq('fresh NSE print: ● NSE', chip({}).text, '● NSE')
  eq('NSE print 20 min old at 11:00: ◌ STALE 10:40', [chip({ asOf: '26-Oct-2026 10:40', quoteAt: F.nseTimeToEpoch('26-Oct-2026 10:40') }).text,
    chip({ asOf: '26-Oct-2026 10:40', quoteAt: F.nseTimeToEpoch('26-Oct-2026 10:40') }).tone], ['◌ STALE 10:40', 'down'])
  eq('ICICI stream stopped 10 min ago: ◌ STALE, not ● LIVE', chip({ src: 'ICICI', quoteAt: t - 600_000 }).text, '◌ STALE 10:50')
  eq('negative control: without the quote time the chip says ● NSE on the old value', chip({ asOf: '26-Oct-2026 10:40', quoteAt: undefined }).text, '● NSE')
  eq('pre-open (09:10) and closed hours never say STALE', [
    F.niftySourceChip({ src: 'NSE', wsConnected: false, marketOpen: true, linkDown: false, asOf: '23-Oct-2026 15:30', now: ist('2026-10-26T09:10:00'),
      quoteAt: F.nseTimeToEpoch('23-Oct-2026 15:30') }).text,
    F.niftySourceChip({ src: 'NSE', wsConnected: false, marketOpen: false, linkDown: false, asOf: '23-Oct-2026 15:30', now: ist('2026-10-26T16:00:00'),
      quoteAt: F.nseTimeToEpoch('23-Oct-2026 15:30') }).text], ['● NSE', 'CLOSE 23-OCT'])
  eq('isStaleQuote window', [F.isStaleQuote(t - 299_000, t), F.isStaleQuote(t - 301_000, t), F.isStaleQuote(null, t),
    F.isStaleQuote(ist('2026-10-26T15:20:00'), ist('2026-10-26T15:31:00'))], [false, true, false, false])
  eq('liveQuoteAt: ltt first, else ts (s or ms)', [F.liveQuoteAt({ ts: 1, raw: { ltt: '26-Oct-2026 10:59:00' } }), F.liveQuoteAt({ ts: 1761456540 }),
    F.liveQuoteAt({ ts: 1761456540000 }), F.liveQuoteAt(null), F.liveQuoteAt({ raw: {} })],
    [F.nseTimeToEpoch('26-Oct-2026 10:59:00'), 1761456540000, 1761456540000, null, null])
  const pick = (o: Partial<Parameters<FeedStateMod['pickNiftySource']>[0]>) =>
    F.pickNiftySource({ wsLtp: 24000, wsAt: t - 30_000, nseLast: 24010, nseAt: t - 60_000, storedLtp: 23900, ...o })
  eq('source: ICICI while it streams; NSE once the stream is > 5 min behind NSE; then stored', [pick({}), pick({ wsAt: t - 900_000 }),
    pick({ wsAt: t - 900_000, nseLast: undefined }), pick({ wsLtp: undefined }), pick({ wsLtp: undefined, nseLast: null }),
    pick({ wsLtp: undefined, nseLast: undefined, storedLtp: undefined })], ['ICICI', 'NSE', 'ICICI', 'NSE', 'STALE', null])
  const header = await read('../../MarketCommandHeader.tsx')
  check('header picks the source with pickNiftySource and passes the shown quote time', /const src = pickNiftySource\(\{ wsLtp: ws\?\.ltp, wsAt, nseLast: nse\?\.last, nseAt, storedLtp: rec\?\.ltp \}\)/.test(header)
    && /const quoteAt = src === 'ICICI' \? wsAt : src === 'NSE' \? nseAt : null/.test(header))
  check('macro tape: NSE and Yahoo land independently (allSettled, merged over the last values)', /await Promise\.allSettled\(\[yahoo, nse\]\)/.test(header)
    && !/Promise\.all\(\[getNewsQuotes/.test(header) && (header.match(/setQ\(prev => \{/g) ?? []).length === 2)
  const page = await read('../../../app/page.tsx')
  check('footer DATA / OVRV: summary every 10 min (30 hidden), on focus, and after every outage',
    /usePolling\(pollDashboard, hiddenDoc \? 30 \* 60_000 : DASHBOARD_REFRESH_MS\)/.test(page) && /useOnFocus\(pollDashboard\)/.test(page)
    && /const DASHBOARD_REFRESH_MS = 10 \* 60_000/.test(page) && /r\.loadDashboard\(\)\s+\/\/ P9/.test(page) && !/if \(r\.dashError\) r\.loadDashboard\(\)/.test(page))
}

async function refreshVerdictChecks(): Promise<void> {
  const R = await load<RefreshStatusMod>('../../../lib/refreshStatus.ts')
  // CT-04: COMPLETE only with positive evidence
  eq('ui-api restarted mid-download (empty status): UNKNOWN, never COMPLETE', R.refreshVerdict({ active: false, total: 0, done: 0, current: 0, errors: 0 }, 1500),
    { kind: 'unknown', reason: 'progress was lost (ui-api restarted?)' })
  const oldRule = (st: { active: boolean; errors: number }) => (!st.active ? (st.errors > 0 ? 'COMPLETE · FAILED' : 'COMPLETE') : 'RUNNING')
  check('negative control: the round-3 headline called that status UPDATE COMPLETE', oldRule({ active: false, errors: 0 }) === 'COMPLETE')
  eq('every stock has an outcome: COMPLETE', R.refreshVerdict({ active: false, total: 1500, done: 120, current: 1378, errors: 2 }, 1500), { kind: 'complete', failed: 2 })
  eq('running', R.refreshVerdict({ active: true, total: 1500, done: 3 }, 1500), { kind: 'running' })
  eq('stopped before every stock had a result', R.refreshVerdict({ active: false, total: 1500, done: 10, current: 10, errors: 0 }, 1500).kind, 'unknown')
  eq('a different download (the watchlist refresh) is not this one', R.refreshVerdict({ active: false, total: 12, done: 12, current: 0, errors: 0 }, 1500).kind, 'unknown')
  eq('no expected size (started elsewhere): judged on its own counts', R.refreshVerdict({ active: false, total: 12, done: 12 }, null), { kind: 'complete', failed: 0 })
  eq('no status / junk', [R.refreshVerdict(null).kind, R.refreshVerdict({ active: false, total: 'x' as unknown as number }).kind], ['unknown', 'unknown'])
  const page = await read('../../../app/page.tsx')
  check('the panel says COMPLETE only through refreshVerdict', /const v = refreshVerdict\(p\.status, p\.expectedTotal\)/.test(page)
    && (page.match(/'UPDATE COMPLETE'/g) ?? []).length === 1 && /`UPDATE STATUS UNKNOWN · \$\{v\.reason\}`/.test(page))
  check('PROGRESS UNAVAILABLE names the right process (the download runs in ui-api)', /may still be running in ui-api/.test(page) && !/running in data-service/.test(page))
  check('one poll chain at a time (CHECK AGAIN double-click)', /if \(pollBusy\.current\) return/.test(page) && /if \(pollTimer\.current\) clearTimeout\(pollTimer\.current\)/.test(page)
    && !/setTimeout\(\(\) => \{ void pollRefresh\(\) \}, 3000\)/.test(page))
  check('RETRY UPDATE asks twice inside the EOD window', /if \(inEodWindow\(Date\.now\(\)\) && !armed\) \{ setArmed\(true\); return \}/.test(page) && /CONFIRM: RETRY DURING EOD/.test(page))
  check('the start request size is remembered for the verdict', /expectedTotal\.current = typeof data\?\.tickers === 'number' && data\.tickers > 0 \? data\.tickers : null/.test(page))
}

async function iciciChecks(): Promise<void> {
  const I = await load<IciciStatusMod>('../../../lib/iciciStatus.ts')
  // P4: the kind decides, never needs_session_refresh (it is true during a network outage too)
  const outage = { connected: false, error_kind: 'network', needs_session_refresh: true, needs_api_credentials: false }
  eq('kinds', [I.iciciErrorKind(outage), I.iciciErrorKind({ connected: false, error_kind: 'expired' }), I.iciciErrorKind({ connected: false, error_kind: 'credentials' }),
    I.iciciErrorKind({ connected: false, error_kind: 'weird' }), I.iciciErrorKind({ connected: true, error_kind: null }), I.iciciErrorKind(null),
    I.iciciErrorKind({ connected: false, needs_api_credentials: true }), I.iciciErrorKind({ connected: false, needs_session_refresh: true })],
    ['network', 'expired', 'credentials', 'unknown', null, null, 'credentials', 'unknown'])
  check('network outage never asks for a login', !/\/login|log in/.test(I.iciciLightTitle(false, null, outage)))
  // the BRIEF line is F4B-UI-PAGES's (components/portfolio/iciciState.ts): an outage must not read as an expired session there either
  const pagesHelper = await read('../../portfolio/iciciState.ts').catch(() => '')
  check('BRIEF (pages helper) words a network outage as unreachable, not expired', !pagesHelper || /if \(kind === 'network'\) return 'ICICI unreachable \(network\)/.test(pagesHelper))
  check('header light: network → "ICICI unreachable (network) — not a login problem"', I.iciciLightTitle(false, null, outage).startsWith('ICICI unreachable (network) — not a login problem'))
  check('header light: expired keeps "send /login"', /send \/login/.test(I.iciciLightTitle(false, null, { connected: false, error_kind: 'expired' })))
  check('header light: credentials → "ICICI API key/secret missing"', I.iciciLightTitle(false, null, { connected: false, error_kind: 'credentials' }).startsWith('ICICI API key/secret missing'))
  eq('header light: connected / not read yet', [I.iciciLightTitle(true, 'ICICIBreezeProvider', null), I.iciciLightTitle(false, null, null)],
    ['ICICI Breeze connected (ICICIBreezeProvider)', 'ICICI not connected: click to open the Broker tab'])
  const header = await read('../../MarketCommandHeader.tsx')
  check('header light uses iciciLightTitle and reads connection-status only while red',
    /detail=\{iciciLightTitle\(connected, provider, status\)\}/.test(header) && /const want = known && !connected && !linkDown/.test(header)
    && /needs_api_credentials: r\.data\?\.needs_api_credentials === true/.test(header) && !/login_url/.test(header))
}

async function findChecks(): Promise<void> {
  const F = await load<FindMod>('../find.ts')
  const k = (key: string, o: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) =>
    F.findShortcut({ key, metaKey: true, ctrlKey: false, altKey: false, shiftKey: false, ...o })
  eq('⌘F / ⌘G / ⇧⌘G', [k('f'), k('F'), k('g'), k('G', { shiftKey: true }), k('f', { shiftKey: true }), k('f', { metaKey: false }), k('f', { ctrlKey: true }),
    k('f', { altKey: true }), k('k')], ['open', 'open', 'next', 'prev', null, null, null, null, null])
  eq('match count (case-insensitive, non-overlapping, capped)', [F.countMatches('RELIANCE reliance Reliance', 'reliance'), F.countMatches('aaaa', 'aa'),
    F.countMatches('abc', ''), F.countMatches('x'.repeat(5000), 'x', 999)], [3, 2, 0, 1000])
  eq('status', [F.findStatus('', null, 0), F.findStatus('tcs', false, 0), F.findStatus('tcs', true, 1), F.findStatus('tcs', true, 12), F.findStatus('x', true, 1000)],
    ['', 'NO MATCH', '1 MATCH', '12 MATCHES', '999+ MATCHES'])
  const shell = await read('../PlatformShell.tsx')
  check('the find bar is mounted in the app only (a browser keeps its native ⌘F)', /\{desktop && <FindBar \/>\}/.test(shell))
  const bar = await read('../FindBar.tsx')
  check('find bar: window.find, then focus back in the input, highlight the match', /find\.call\(window, query, false, backwards, true, false, false, false\)/.test(bar)
    && /refocus\(\)/.test(bar) && /setHighlight\(inBar \? null : r\)/.test(bar))
  check('find bar: Esc closes it without closing the stock window; not a dialog (type-to-GO keeps working)',
    /if \(e\.key === 'Escape'\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); close\(\); return \}/.test(bar) && /role="search"/.test(bar) && !/role="dialog"/.test(bar))
  const css = await read('../../../app/globals.css')
  check('find bar labels are generated content (a search never matches the bar)', /\.sd-find-tag::before \{ content: 'FIND'; \}/.test(css)
    && /\.sd-find-status::before \{ content: attr\(data-status\); \}/.test(css) && /::highlight\(sd-find\)/.test(css))
  const K = await load<ShortcutsMod>('../../../lib/shortcuts.ts')
  check('help teaches ⌘F in the app only', K.helpKeys(true).some(([key]) => /⌘ F/.test(key)) && !K.helpKeys(false, true).some(([key]) => /⌘ F/.test(key)))
}

async function downloadToastChecks(): Promise<void> {
  const D = await load<DownloadTextMod>('../../../lib/downloadText.ts')
  eq('success: tilde path + ⌥⌘L', D.downloadToast({ ok: true, filename: 'desk.csv', path: '/Users/sudheer/Downloads/desk (2).csv' }),
    { text: 'Saved to ~/Downloads/desk (2).csv · ⌥⌘L shows it in Finder', type: 'success', ttl: 7000 })
  eq('success without a path', D.downloadToast({ ok: true, filename: 'x.csv' }).text, 'Saved to ~/Downloads/x.csv · ⌥⌘L shows it in Finder')
  eq('failure: the reason', D.downloadToast({ ok: false, filename: 'big.csv', error: 'file is larger than 50 MB' }),
    { text: 'big.csv NOT saved: file is larger than 50 MB', type: 'error', ttl: 15000 })
  eq('failure without a reason', D.downloadToast({ ok: false, filename: 'x.csv' }).text, 'x.csv NOT saved: the save failed')
  eq('other paths unchanged', D.tildePath('/private/tmp/a.csv'), '/private/tmp/a.csv')
  const toasts = await read('../../shell/ShellToasts.tsx')
  check('DownloadToasts listens to the shell save event', /window\.addEventListener\(DOWNLOAD_EVENT, on\)/.test(toasts) && /addToast\(t\.text, t\.type, t\.ttl\)/.test(toasts))
  const plat = await read('../../../lib/platform/index.ts')
  check('browser downloads emit nothing (unchanged): only desktop paths call emitDownload',
    (plat.match(/emitDownload\(/g) ?? []).length === 5 && /if \(isDesktop\(\)\) return desktopSave\(blob, filename\)/.test(plat))
}

async function goSanitizeChecks(): Promise<void> {
  const A = await load<GoAliasesMod>('../../../lib/goAliases.ts')
  const rows = [{ t: 'TCS', n: 'Tata Consultancy', s: 'IT', c: null }, { t: 'NEWCO', n: null, s: null, c: null }, { t: 'X', n: 7 }, null, { n: 'no ticker' },
    { t: '', n: 'blank' }, { t: 5, n: 'numeric ticker' }, 'junk']
  const out = A.sanitizeSymbolRows<{ t: string; n: string }>(rows)
  eq('P15: rows without a ticker dropped, a null / non-string name reads ""', out.map(r => [r.t, r.n]), [['TCS', 'Tata Consultancy'], ['NEWCO', ''], ['X', '']])
  check('P15: the name filter no longer throws', (() => { try { out.filter(s => s.n.toUpperCase().includes('TATA')); return true } catch { return false } })())
  check('negative control: the pre-fix filter throws on a null name', (() => {
    try { (rows.filter(r => r && typeof r === 'object' && 'n' in r) as Array<{ n: string }>).filter(s => s.n.toUpperCase().includes('X')); return false } catch { return true }
  })())
  eq('not a list → empty', [A.sanitizeSymbolRows(null).length, A.sanitizeSymbolRows({ data: [] }).length], [0, 0])
}

for (const [name, fn] of [['session', sessionChecks], ['status', statusChecks], ['pages', pagesChecks], ['health', healthChecks],
  ['build', buildChecks], ['chunkRecovery', chunkChecks], ['location', locationChecks],
  ['clientErrors', clientErrorChecks], ['deepLink', deepLinkChecks], ['shortcuts', shortcutChecks], ['reconnect', reconnectChecks],
  ['bootstrapGate', bootstrapGateChecks], ['chrome', chromeChecks], ['zoom', zoomChecks], ['sharedFetch', sharedFetchChecks],
  ['holidayStore', holidayStoreChecks], ['feedState', feedChecks], ['specialSession', specialSessionChecks], ['liveFeed', liveFeedChecks],
  ['goAliases', goAliasChecks], ['macKeys', macKeyChecks], ['outage', outageChecks], ['boundary', boundaryChecks], ['shellUx', shellUxChecks],
  ['liveEvidence', liveEvidenceChecks], ['priceMarker', priceMarkerChecks], ['staleQuote', staleQuoteChecks], ['refreshVerdict', refreshVerdictChecks],
  ['icici', iciciChecks], ['find', findChecks], ['downloadToast', downloadToastChecks], ['goSanitize', goSanitizeChecks]] as const) {
  try {
    await fn()
  } catch (e) {
    failures++
    console.error(`FAIL ${name} threw: ${e instanceof Error ? e.stack : String(e)}`)
  }
}
console.log(`desktop.check: ${passes} passed, ${failures} failed`)
if (failures) process.exit(1)
