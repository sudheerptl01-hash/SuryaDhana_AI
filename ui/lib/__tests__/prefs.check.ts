/**
 * Prefs client checks (desktop program D3): key inventory, per-key LWW planning, and the sync engine
 * end-to-end against an in-memory port of routers/prefs.py semantics (fake storage + fake timers).
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/prefs.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on the first failing group.
 */
import * as nodeModule from 'node:module'
import * as fs from 'node:fs'
import * as path from 'node:path'

// Extensionless relative specifiers (the app's import style) -> .ts, for node's ESM resolver.
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

const keys = await import('../prefs/keys')
const merge = await import('../prefs/merge')
const sync = await import('../prefs/sync')
const external = await import('../prefs/external')
const migration = await import('../prefs/migration')
type ServerPrefs = import('../prefs/merge').ServerPrefs
type ResponseLike = import('../prefs/sync').ResponseLike

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

// ── 1. key inventory ───────────────────────────────────────────────────────────────────────────
{
  const sync_ = new Set<string>(keys.SYNC_KEYS)
  for (const k of keys.SYNC_KEYS) check(`sync key ${k} passes the server key rule`, keys.SERVER_KEY_RE.test(k))
  for (const k of keys.LOCAL_KEYS) check(`local key ${k} is not also SYNC`, !sync_.has(k))
  check('bookkeeping keys are LOCAL', [keys.PREFS_META_KEY, keys.PREFS_HASH_KEY, keys.PREFS_DIRTY_KEY].every((k) => keys.classifyKey(k) === 'local'))
  check('unknown keys are not synced', !keys.isSyncKey('random.key') && keys.classifyKey('random.key') === 'unknown')
  // Regression guard: every storage-key literal in a file that touches localStorage is classified.
  const uiRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
  const literal = /['"`]((?:suryadhana|newsTerminal|goldPreOpen)\.[A-Za-z0-9._:-]+|theme)['"`]/g
  const unclassified: string[] = []
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name.startsWith('.') || e.name === '__tests__') continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.(ts|tsx)$/.test(e.name) && !p.includes(`${path.sep}lib${path.sep}prefs${path.sep}`)) {
        const src = fs.readFileSync(p, 'utf8')
        if (!src.includes('localStorage')) continue
        for (const m of src.matchAll(literal)) {
          const k = m[1]
          if (k === 'theme' && !/localStorage\.\w+\(\s*['"]theme['"]/.test(src)) continue
          if (keys.classifyKey(k) === 'unknown') unclassified.push(`${path.relative(uiRoot, p)}: ${k}`)
        }
      }
    }
  }
  for (const d of ['app', 'components', 'context', 'lib']) {
    const full = path.join(uiRoot, d)
    if (fs.existsSync(full)) walk(full)
  }
  check('every localStorage key literal in ui/ is classified (add it to lib/prefs/keys.ts)', unclassified.length === 0, unclassified)
}

// ── 2. planHydration matrix ────────────────────────────────────────────────────────────────────
{
  const K = ['w', 'p']
  const rec = (value: string | null, updated_at: number) => ({ value, updated_at, deleted: value === null })
  const H = merge.hashValue
  const plan = (server: ServerPrefs, values: Record<string, string | null>, meta: Record<string, number> = {},
    hash: Record<string, string> = {}, dirty: Record<string, number> = {}, legacy: string[] = []) =>
    merge.planHydration(K, server, { values, meta, hash, dirty, legacy })

  let p = plan({ w: rec('["A"]', 10) }, {})
  check('fresh device adopts the server value', p.apply.length === 1 && p.apply[0].value === '["A"]' && !p.upload.length && !Object.keys(p.imports).length, p)

  p = plan({}, { w: '["L"]' }, {}, {}, {}, ['w'])
  check('legacy value, server absent -> legacy import', p.imports.w === '["L"]' && !p.apply.length && !p.upload.length && !('w' in p.provisional), p)

  p = plan({ w: rec('["S"]', 10) }, { w: '["L"]' }, {}, {}, {}, ['w'])
  check('legacy value, server present -> still offered (server decides), not applied yet', p.imports.w === '["L"]' && !p.apply.length, p)

  p = plan({}, { w: '[]' }, {}, {}, { w: 5 })
  check('never-synced post-install value, server absent -> provisional import', p.provisional.w === '[]' && !('w' in p.imports) && p.clean.includes('w'), p)

  p = plan({ w: rec('["S"]', 10) }, { w: '[]' })
  check('never-synced post-install value, server present -> server wins', p.apply[0]?.value === '["S"]' && !('w' in p.provisional), p)

  p = plan({ w: rec('["S"]', 10) }, { w: null }, {}, {}, {}, ['w'])
  check('legacy key removed locally before first sync -> adopt server', p.apply[0]?.value === '["S"]' && !('w' in p.imports), p)

  p = plan({ w: rec('["S"]', 10) }, { w: '[]' }, {}, {}, { w: 99999 })
  check('never-synced key with a newer local write still adopts the server (empty origin cannot wipe)', p.apply[0]?.value === '["S"]' && !p.upload.length, p)

  p = plan({ w: rec('new', 20) }, { w: 'old' }, { w: 10 }, { w: H('old') })
  check('clean + server newer -> apply', p.apply[0]?.value === 'new', p)
  p = plan({ w: rec('old', 5) }, { w: 'cur' }, { w: 10 }, { w: H('cur') })
  check('clean + server older (restored backup) -> re-upload with meta stamp', p.upload[0]?.updated_at === 10 && !p.apply.length, p)
  p = plan({ w: rec('cur', 10) }, { w: 'cur' }, { w: 10 }, { w: H('cur') })
  check('clean + equal -> nothing', !p.apply.length && !p.upload.length && !p.clean.length, p)

  p = plan({ w: rec('srv', 15) }, { w: 'mine' }, { w: 10 }, { w: H('old') }, { w: 30 })
  check('local change newer than server change -> upload', p.upload[0]?.updated_at === 30 && !p.apply.length, p)
  p = plan({ w: rec('srv', 40) }, { w: 'mine' }, { w: 10 }, { w: H('old') }, { w: 30 })
  check('server change newer than local change -> apply', p.apply[0]?.value === 'srv' && !p.upload.length, p)

  p = plan({ w: rec('cur', 10) }, { w: 'cur' }, { w: 10 }, { w: H('cur') }, { w: 30 })
  check('transient write (back to the synced value) -> clean, no upload', p.clean.includes('w') && !p.upload.length, p)

  p = plan({}, { w: 'cur' }, { w: 10 }, { w: H('cur') })
  check('server lost a synced key -> restore upload', p.upload[0]?.key === 'w' && p.upload[0]?.updated_at === 10, p)
  p = plan({}, { w: null }, { w: 10 }, { w: H(null) })
  check('server lost a key deleted here -> nothing', !p.upload.length && !p.apply.length, p)

  p = plan({ w: rec(null, 50) }, { w: 'cur' }, { w: 10 }, { w: H('cur') })
  check('server tombstone newer -> local delete', p.apply[0]?.value === null && p.apply[0]?.updated_at === 50, p)

  p = plan({ w: rec('x', 10) }, { w: 'x' }, { w: 10 }, { w: H('x') }, { w: 10 })
  check('forced re-upload already satisfied (server equal) -> adopt', p.apply[0]?.updated_at === 10 && !p.upload.length, p)

  p = merge.planHydration(['w'], { other: rec('z', 1) } as ServerPrefs, { values: {}, meta: {}, hash: {}, dirty: {} })
  check('server keys outside the allowlist are ignored', !p.apply.length, p)

  check('hash distinguishes null, empty and text', new Set([H(null), H(''), H('a'), H('b')]).size === 4)
  check('nextStamp is strictly monotonic per key', merge.nextStamp(5, 10, 12) === 13 && merge.nextStamp(100, 10) === 100)
  const bad = merge.sanitizeServerPrefs({ a: { value: 'x', updated_at: 1, deleted: false }, b: { value: 5, updated_at: 1, deleted: false }, c: null, d: { deleted: true, updated_at: 3, value: null } })
  check('sanitizeServerPrefs drops malformed records', Object.keys(bad).sort().join() === 'a,d', bad)
}

// ── 3. engine end-to-end against an in-memory server ───────────────────────────────────────────

/** routers/prefs.py semantics in miniature (LWW, idempotent replay, tombstones, fill-only import). */
class FakeServer {
  recs: Record<string, { value: string | null; updated_at: number; deleted: boolean }> = {}
  provisional = new Set<string>()
  importKinds: string[] = []
  log: string[] = []
  down = false
  missing = false // simulates an old ui-api without the router (404)
  maxBytes = 256 * 1024
  clock = 1_000_000
  private res(status: number, body: unknown): ResponseLike {
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  }
  fetch = async (url: string, init: RequestInit = {}): Promise<ResponseLike> => {
    await Promise.resolve()
    if (this.down) throw new TypeError('Failed to fetch')
    const method = (init.method || 'GET').toUpperCase()
    const u = new URL(url, 'http://127.0.0.1:8010')
    this.log.push(`${method} ${u.pathname}`)
    if (this.missing) return this.res(404, { detail: 'Not Found', error: { code: 'not_found', message: 'Not Found' } })
    const parts = u.pathname.split('/').filter(Boolean) // api, prefs, [key|import]
    if (method === 'GET' && parts.length === 2) return this.res(200, { prefs: structuredClone(this.recs), server_time: this.clock })
    if (method === 'POST' && parts[2] === 'import') {
      const body = JSON.parse(String(init.body)) as { items: Record<string, string>; provisional?: boolean }
      this.importKinds.push(body.provisional ? 'provisional' : 'legacy')
      const imported: string[] = []
      const skipped: string[] = []
      const rejected: Record<string, string> = {}
      for (const [k, v] of Object.entries(body.items)) {
        const cur = this.recs[k]
        const replace = !!cur && !body.provisional && this.provisional.has(k) && !cur.deleted
        if (v.length > this.maxBytes) rejected[k] = 'too large'
        else if (cur && !replace) skipped.push(k)
        else {
          this.recs[k] = { value: v, updated_at: Math.max(++this.clock, (cur?.updated_at ?? 0) + 1), deleted: false }
          if (body.provisional) this.provisional.add(k)
          else this.provisional.delete(k)
          imported.push(k)
        }
      }
      const prefs: Record<string, unknown> = {}
      for (const k of Object.keys(body.items)) if (this.recs[k]) prefs[k] = this.recs[k]
      return this.res(200, { imported, skipped, rejected, prefs, server_time: this.clock })
    }
    const key = decodeURIComponent(parts[2] || '')
    const cur = this.recs[key]
    let value: string | null
    let ts: number
    if (method === 'PUT') {
      const body = JSON.parse(String(init.body)) as { value: string; updated_at: number }
      value = body.value
      ts = body.updated_at
      if (value.length > this.maxBytes) return this.res(413, { detail: 'too large', error: { code: 'invalid', message: 'too large' } })
    } else if (method === 'DELETE') {
      value = null
      ts = Number(u.searchParams.get('updated_at'))
    } else return this.res(405, {})
    if (cur) {
      const same = cur.deleted === (value === null) && (value === null || cur.value === value)
      if (ts < cur.updated_at || (ts === cur.updated_at && !same)) return this.res(409, { detail: 'newer', error: { code: 'state', message: 'newer' }, current: cur, key })
      if (ts === cur.updated_at && same) return this.res(200, { key, pref: cur })
    }
    this.recs[key] = { value, updated_at: ts, deleted: value === null }
    this.provisional.delete(key) // a deliberate write is never provisional
    return this.res(200, { key, pref: this.recs[key] })
  }
  writes(): string[] {
    return this.log.filter((l) => !l.startsWith('GET'))
  }
}

/** Storage stand-in with prototype methods (so the prototype wrapper is exercised). */
class FakeStorage {
  private m = new Map<string, string>()
  getItem(k: string): string | null {
    return this.m.has(k) ? this.m.get(k)! : null
  }
  setItem(k: string, v: string): void {
    this.m.set(String(k), String(v))
  }
  removeItem(k: string): void {
    this.m.delete(String(k))
  }
}

class Clock {
  now = 2_000_000
  private timers: Array<{ at: number; fn: () => void; id: number }> = []
  private seq = 0
  set = (fn: () => void, ms: number) => {
    const id = ++this.seq
    this.timers.push({ at: this.now + Math.max(0, ms), fn, id })
    return id
  }
  clear = (h: unknown) => {
    this.timers = this.timers.filter((t) => t.id !== h)
  }
  async advance(ms: number): Promise<void> {
    const end = this.now + ms
    for (;;) {
      await settle()
      this.timers.sort((a, b) => a.at - b.at)
      const t = this.timers[0]
      if (!t || t.at > end) break
      this.timers.shift()
      this.now = Math.max(this.now, t.at)
      t.fn()
    }
    this.now = end
    await settle()
  }
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await new Promise<void>((r) => setImmediate(r))
}

function makeWindow(server: FakeServer, clock: Clock, storage: FakeStorage, label: string) {
  const applied: string[][] = []
  const raw = sync.originalMethods(FakeStorage.prototype)
  const engine = new sync.PrefsSyncEngine({
    storage: { getItem: (k) => raw.getItem.call(storage, k), setItem: (k, v) => raw.setItem.call(storage, k, v), removeItem: (k) => raw.removeItem.call(storage, k) },
    fetch: server.fetch,
    apiBase: '',
    origin: `http://${label}`,
    now: () => clock.now,
    setTimer: clock.set,
    clearTimer: clock.clear,
    onApplied: (changes) => applied.push(changes.map((c) => c.key)),
  })
  engine.snapshotLegacy() // what ensureEngine() does when the page engine is created
  return { engine, applied }
}

const W = 'suryadhana.watchlist'
const PINS = 'newsTerminal.pins.v1'
const SEEN = 'suryadhana.alerts.seen.v2'
const RECENT_KEY_CHECK = 'suryadhana.cmd.recent.v1'

{
  const server = new FakeServer()
  const clock = new Clock()
  // One observer per storage instance: route changes to the engine that owns that storage.
  const owners = new Map<object, (k: string) => void>()
  const uninstall = sync.installWriteThroughOn(FakeStorage.prototype, {}, () => {})
  uninstall()
  // The real wrapper observes exactly one target; multiplex here so several fake origins can share the prototype.
  const proto = FakeStorage.prototype as unknown as { setItem: (k: string, v: string) => void; removeItem: (k: string) => void; getItem: (k: string) => string | null }
  const origSet = proto.setItem
  const origRemove = proto.removeItem
  proto.setItem = function (this: FakeStorage, k: string, v: string) {
    const old = this.getItem(k)
    origSet.call(this, k, v)
    if (keys.isSyncKey(k) && old !== String(v)) owners.get(this)?.(k)
  }
  proto.removeItem = function (this: FakeStorage, k: string) {
    const old = this.getItem(k)
    origRemove.call(this, k)
    if (keys.isSyncKey(k) && old !== null) owners.get(this)?.(k)
  }

  // E1 — migration from the old browser origin (legacy keys, no meta).
  const oldOrigin = new FakeStorage()
  origSet.call(oldOrigin, W, '["TCS","INFY"]')
  origSet.call(oldOrigin, PINS, '{"TCS.NS":{"pinned_at":"x"}}')
  origSet.call(oldOrigin, SEEN, '2026-10-20T10:00')
  origSet.call(oldOrigin, RECENT_KEY_CHECK, '["SBIN"]')
  const A = makeWindow(server, clock, oldOrigin, 'old')
  owners.set(oldOrigin, (k) => A.engine.noteLocalChange(k))
  let h = await A.engine.hydrate({ timeoutMs: 1500, emit: false })
  await h.importDone
  check('E1 migration hydrate ok', h.result === 'ok', h.result)
  check('E1 legacy SYNC keys imported', server.recs[W]?.value === '["TCS","INFY"]' && !!server.recs[PINS], server.recs)
  check('E1 LOCAL key never leaves the device', !(SEEN in server.recs))
  check('E1 meta recorded for imported keys', JSON.parse(oldOrigin.getItem(keys.PREFS_META_KEY) || '{}')[W] === server.recs[W].updated_at)
  check('E1 exactly one import request, a legacy one', server.writes().join() === 'POST /api/prefs/import' && server.importKinds.join() === 'legacy', [server.writes(), server.importKinds])
  check('E1 legacy snapshot recorded on the old origin', JSON.parse(oldOrigin.getItem(keys.PREFS_LEGACY_KEY) || '[]').sort().join() === [PINS, RECENT_KEY_CHECK, W].sort().join(), oldOrigin.getItem(keys.PREFS_LEGACY_KEY))

  // E2 — the desktop app (new, empty origin) hydrates before render.
  const app = new FakeStorage()
  const B = makeWindow(server, clock, app, 'app')
  owners.set(app, (k) => B.engine.noteLocalChange(k))
  server.log = []
  h = await B.engine.hydrate({ timeoutMs: 1500, emit: false })
  await h.importDone
  check('E2 app adopts watchlist + pins', app.getItem(W) === '["TCS","INFY"]' && app.getItem(PINS) === '{"TCS.NS":{"pinned_at":"x"}}')
  check('E2 boot hydration emits nothing and uploads nothing', B.applied.length === 0 && server.writes().length === 0, server.log)

  // E3 — write-through, debounced into a single PUT.
  server.log = []
  clock.now += 1000
  app.setItem(W, '["TCS","INFY","HDFCBANK"]')
  app.setItem(W, '["TCS","INFY","HDFCBANK","SBIN"]')
  await clock.advance(100)
  check('E3 nothing sent before the debounce', server.writes().length === 0, server.log)
  await clock.advance(400)
  check('E3 one PUT after the debounce', server.writes().join() === `PUT /api/prefs/${W}`, server.log)
  check('E3 server has the latest value', server.recs[W].value === '["TCS","INFY","HDFCBANK","SBIN"]')
  check('E3 dirty queue empty', Object.keys(JSON.parse(app.getItem(keys.PREFS_DIRTY_KEY) || '{}')).length === 0)

  // E4 — the browser window refetches on focus: applies, emits, never re-uploads (no ping-pong).
  server.log = []
  clock.now += 5000
  const r4 = await A.engine.refetch()
  await clock.advance(1000)
  check('E4 refetch ok', r4 === 'ok', r4)
  check('E4 browser got the app change', oldOrigin.getItem(W) === '["TCS","INFY","HDFCBANK","SBIN"]')
  check('E4 prefs-changed emitted with the key', A.applied.length === 1 && A.applied[0].join() === W, A.applied)
  check('E4 no upload from applying server values', server.writes().length === 0, server.log)

  // E5 — unchanged values, non-sync keys and other Storage instances are not observed.
  server.log = []
  app.setItem(W, app.getItem(W)!)
  app.setItem(SEEN, 'x')
  app.setItem('some.other.key', 'y')
  const session = new FakeStorage()
  session.setItem(W, 'session-only')
  await clock.advance(3000)
  check('E5 no uploads for no-op / LOCAL / unknown keys / other storage', server.writes().length === 0, server.log)

  // E6 — AppContext's transient '[]' write followed by the real list coalesces to nothing.
  server.log = []
  const before = app.getItem(W)!
  app.setItem(W, '[]')
  app.setItem(W, before)
  await clock.advance(3000)
  check('E6 transient write produces no PUT', server.writes().length === 0, server.log)

  // E7 — offline: the change is queued (persisted), retried with backoff, uploaded when back.
  server.log = []
  server.down = true
  clock.now += 1000
  app.setItem(PINS, '{}')
  await clock.advance(5000)
  check('E7 still dirty while offline', PINS in JSON.parse(app.getItem(keys.PREFS_DIRTY_KEY) || '{}'))
  server.down = false
  await clock.advance(70_000)
  check('E7 uploaded after reconnect', server.recs[PINS]?.value === '{}', server.recs[PINS])
  check('E7 dirty cleared', !(PINS in JSON.parse(app.getItem(keys.PREFS_DIRTY_KEY) || '{}')))

  // E8 — conflict: another device wrote a newer value; a stale local write gets 409 and adopts it.
  server.log = []
  server.recs[W] = { value: '["FROM-IPAD"]', updated_at: clock.now + 10_000, deleted: false }
  app.setItem(W, '["STALE-EDIT"]')
  await clock.advance(1000)
  check('E8 409 -> server value adopted locally', app.getItem(W) === '["FROM-IPAD"]', app.getItem(W))
  check('E8 server kept the newer value', server.recs[W].value === '["FROM-IPAD"]')
  check('E8 emitted a change event', B.applied.some((ks) => ks.includes(W)))

  // E9 — two windows on ONE storage (same origin): one upload, the second window does nothing.
  server.log = []
  const B2 = makeWindow(server, clock, app, 'app-window-2')
  clock.now = Math.max(clock.now, server.recs[W].updated_at) + 1000
  app.setItem(W, '["NINE"]')
  await clock.advance(1000) // window 1 flushes
  const r9 = await B2.engine.refetch(true)
  await B2.engine.flush()
  await clock.advance(5000)
  let puts = server.writes().filter((l) => l === `PUT /api/prefs/${W}`)
  check('E9 refetch in window 2 ok', r9 === 'ok', r9)
  check('E9 exactly one PUT across both windows', puts.length === 1, server.log)
  check('E9 window 2 applied nothing (already current)', B2.applied.length === 0, B2.applied)
  // Race: window 2 refetches BEFORE window 1's debounce fires; both may send, never a 409/loop.
  server.log = []
  clock.now += 1000
  app.setItem(W, '["NINE","TEN"]')
  await B2.engine.refetch(true)
  await clock.advance(10_000)
  puts = server.writes().filter((l) => l === `PUT /api/prefs/${W}`)
  check('E9 race: at most two identical PUTs', puts.length >= 1 && puts.length <= 2, server.log)
  check('E9 race: server has the edit', server.recs[W].value === '["NINE","TEN"]')
  check('E9 race: queue drained, nothing adopted back', !(W in JSON.parse(app.getItem(keys.PREFS_DIRTY_KEY) || '{}')) && app.getItem(W) === '["NINE","TEN"]')
  const quiet = server.log.length
  await clock.advance(120_000)
  check('E9 race: quiescent afterwards (no ping-pong)', server.log.length === quiet, server.log)

  // E10 — an empty origin writes before hydration (timeout): never wipes the server.
  server.log = []
  const fresh = new FakeStorage()
  const C = makeWindow(server, clock, fresh, 'fresh')
  owners.set(fresh, (k) => C.engine.noteLocalChange(k))
  fresh.setItem(W, '[]') // AppContext persisting its empty initial state
  await clock.advance(3000)
  check('E10 never-synced dirty key is not PUT', server.writes().length === 0, server.log)
  h = await C.engine.hydrate({ timeoutMs: 1500, emit: true })
  await h.importDone
  check('E10 hydration restores the server watchlist', fresh.getItem(W) === '["NINE","TEN"]', fresh.getItem(W))
  check('E10 the replaced unsynced local value is backed up locally', JSON.parse(fresh.getItem(keys.PREFS_BACKUP_KEY) || '{}')[W]?.value === '[]')
  check('E10 server watchlist intact', server.recs[W].value === '["NINE","TEN"]')

  // E11 — deletes propagate as tombstones.
  server.log = []
  clock.now = Math.max(clock.now, server.recs[W].updated_at) + 1000
  app.removeItem(PINS)
  await clock.advance(1000)
  check('E11 DELETE sent', server.writes().some((l) => l === `DELETE /api/prefs/${PINS}`), server.log)
  check('E11 tombstone stored', server.recs[PINS]?.deleted === true)
  clock.now += 5000
  await A.engine.refetch(true)
  check('E11 other origin removed the key', oldOrigin.getItem(PINS) === null)

  // E12 — old ui-api without the router: dormant, no hammering.
  server.log = []
  server.missing = true
  const D = makeWindow(server, clock, new FakeStorage(), 'old-api')
  const r12 = await D.engine.hydrate({ timeoutMs: 1500, emit: false })
  const r12b = await D.engine.refetch(true)
  check('E12 404 -> unsupported, then backoff without requests', r12.result === 'unsupported' && r12b === 'unsupported' && server.log.length === 1, server.log)
  server.missing = false

  // E13 — the server refuses a value (413): dropped from the queue, kept locally, no retry storm.
  server.log = []
  server.maxBytes = 10
  clock.now += 1000
  app.setItem('suryadhana.fund.filters.v1', '{"preset":"all"}')
  // never-synced key: it must go through hydration/import first
  await B.engine.refetch(true)
  await clock.advance(120_000)
  const tries = server.log.filter((l) => l.includes('import')).length
  check('E13 oversized legacy value rejected once, kept locally', tries === 1 && app.getItem('suryadhana.fund.filters.v1') === '{"preset":"all"}', server.log)
  server.maxBytes = 256 * 1024

  // E15 — the desktop app is opened BEFORE the old browser migrates: its defaults must not win.
  {
    const srv2 = new FakeServer()
    const clk = new Clock()
    const appS = new FakeStorage()
    const X = makeWindow(srv2, clk, appS, 'app-first')
    owners.set(appS, (k) => X.engine.noteLocalChange(k))
    let r = await X.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r.importDone
    check('E15 fresh app origin snapshot has no legacy keys', appS.getItem(keys.PREFS_LEGACY_KEY) === '[]')
    appS.setItem(W, '[]') // AppContext persisting its empty initial state
    appS.setItem('suryadhana.fund.hideflagged', '0') // a page persisting its default
    clk.now += 5000
    await X.engine.refetch(true)
    await clk.advance(1000)
    check('E15 app defaults went up as a PROVISIONAL import', srv2.importKinds.join() === 'provisional' && srv2.recs[W]?.value === '[]' && srv2.provisional.has(W), [srv2.importKinds, srv2.recs])
    const oldS = new FakeStorage()
    origSet.call(oldS, W, '["TCS","INFY"]')
    origSet.call(oldS, 'suryadhana.fund.hideflagged', '1')
    const Y = makeWindow(srv2, clk, oldS, 'old-later')
    owners.set(oldS, (k) => Y.engine.noteLocalChange(k))
    r = await Y.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r.importDone
    check('E15 old origin legacy import replaced the provisional defaults', srv2.recs[W].value === '["TCS","INFY"]' && srv2.recs['suryadhana.fund.hideflagged'].value === '1', srv2.recs)
    check('E15 old origin kept its own values', oldS.getItem(W) === '["TCS","INFY"]' && oldS.getItem('suryadhana.fund.hideflagged') === '1')
    clk.now += 5000
    await X.engine.refetch(true)
    check('E15 the app adopts the migrated watchlist on its next sync', appS.getItem(W) === '["TCS","INFY"]' && X.applied.some((ks) => ks.includes(W)), appS.getItem(W))

    // E16 — a deliberate edit in the app before migration wins (LWW); the legacy copy is kept locally.
    const srv3 = new FakeServer()
    const appT = new FakeStorage()
    const X2 = makeWindow(srv3, clk, appT, 'app-edit')
    owners.set(appT, (k) => X2.engine.noteLocalChange(k))
    r = await X2.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r.importDone
    appT.setItem(W, '[]')
    clk.now += 5000
    await X2.engine.refetch(true)
    await clk.advance(1000)
    clk.now += 1000
    appT.setItem(W, '["SBIN"]') // the owner adds a stock in the app
    await clk.advance(1000)
    check('E16 deliberate app edit is a normal PUT (non-provisional)', srv3.recs[W].value === '["SBIN"]' && !srv3.provisional.has(W), srv3.recs[W])
    const oldT = new FakeStorage()
    origSet.call(oldT, W, '["TCS","INFY"]')
    const Y2 = makeWindow(srv3, clk, oldT, 'old-after-edit')
    r = await Y2.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r.importDone
    check('E16 old origin adopts the deliberate edit', oldT.getItem(W) === '["SBIN"]' && srv3.recs[W].value === '["SBIN"]')
    check('E16 old origin legacy watchlist backed up locally', JSON.parse(oldT.getItem(keys.PREFS_BACKUP_KEY) || '{}')[W]?.value === '["TCS","INFY"]')

    // E17 — readonly mode (QA audits against live): reads, never writes.
    const srv4 = new FakeServer()
    srv4.recs[W] = { value: '["LIVE"]', updated_at: 5, deleted: false }
    const qa = new FakeStorage()
    origSet.call(qa, keys.PREFS_MODE_KEY, 'readonly')
    origSet.call(qa, PINS, '{"LOCAL.NS":{}}')
    const Q = makeWindow(srv4, clk, qa, 'qa')
    owners.set(qa, (k) => Q.engine.noteLocalChange(k))
    r = await Q.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r.importDone
    check('E17 readonly: server values applied', r.result === 'ok' && qa.getItem(W) === '["LIVE"]' && srv4.log.some((l) => l.startsWith('GET')), qa.getItem(W))
    qa.setItem(W, '["QA-CLICK"]')
    await clk.advance(5000)
    await Q.engine.flush()
    await Q.engine.refetch(true)
    await clk.advance(5000)
    check('E17 readonly: no import / PUT / DELETE ever', srv4.writes().length === 0 && srv4.recs[W].value === '["LIVE"]', srv4.log)
    check('E17 readonly: status reports the mode', Q.engine.getStatus().mode === 'readonly')

    // E18 — off: no requests at all.
    const srv5 = new FakeServer()
    const off = new FakeStorage()
    origSet.call(off, keys.PREFS_MODE_KEY, 'off')
    const O = makeWindow(srv5, clk, off, 'off')
    const r18 = await O.engine.hydrate({ timeoutMs: 1500, emit: false })
    check('E18 off: no requests', r18.result === 'off' && srv5.log.length === 0, srv5.log)
  }

  // E19 — first-ever edit in a window that never loses focus: reconciled from the flush, no focus needed.
  {
    const srv6 = new FakeServer()
    const clk6 = new Clock()
    const st6 = new FakeStorage()
    const F = makeWindow(srv6, clk6, st6, 'focused')
    owners.set(st6, (k) => F.engine.noteLocalChange(k))
    const r19 = await F.engine.hydrate({ timeoutMs: 1500, emit: false })
    await r19.importDone
    clk6.now += 1000
    st6.setItem(W, '["FIRST"]')
    await clk6.advance(2000)
    check('E19 first edit reaches the server without a focus event', srv6.recs[W]?.value === '["FIRST"]', [srv6.log, srv6.recs])
    clk6.now += 1000
    st6.setItem(W, '["FIRST","SECOND"]')
    await clk6.advance(2000)
    check('E19 the next edit is a plain PUT', srv6.recs[W]?.value === '["FIRST","SECOND"]' && srv6.log.filter((l) => l.startsWith('PUT')).length === 1, srv6.log)
    const n19 = srv6.log.length
    await clk6.advance(120_000)
    check('E19 quiescent afterwards', srv6.log.length === n19, srv6.log)
  }

  // E14 — the real prototype wrapper: observes only its target, keeps QuotaExceeded semantics.
  proto.setItem = origSet
  proto.removeItem = origRemove
  const target = new FakeStorage()
  const other = new FakeStorage()
  const seen: string[] = []
  const un = sync.installWriteThroughOn(proto, target, (k) => seen.push(k))
  target.setItem(W, 'a')
  target.setItem(W, 'a') // unchanged
  target.setItem('not.synced', 'b')
  other.setItem(W, 'c')
  target.removeItem(W)
  target.removeItem(W) // already absent
  check('E14 wrapper observes only real SYNC changes on its target', seen.join() === `${W},${W}`, seen)
  const again = sync.installWriteThroughOn(proto, target, (k) => seen.push(`2:${k}`))
  target.setItem(PINS, 'x')
  check('E14 re-install retargets instead of double-wrapping', seen[seen.length - 1] === `2:${PINS}` && seen.length === 3, seen)
  const throwing = new FakeStorage()
  const un2 = (again(), sync.installWriteThroughOn(proto, throwing, () => { throw new Error('observer bug') }))
  let threw = false
  try {
    throwing.setItem(W, 'z')
  } catch {
    threw = true
  }
  check('E14 an observer error never reaches the caller', !threw && throwing.getItem(W) === 'z')
  un2()
  check('E14 uninstall restores the original methods', proto.setItem === origSet && proto.removeItem === origRemove)
  void un
}

// ── 4. external-change matcher (multi-window consumers, C3-02) ─────────────────────────────────
{
  const LS = { area: 'local' }
  const SS = { area: 'session' }
  const E = external.externalChange
  const watch = [W, 'suryadhana.ticket.v1']
  check('X1 native storage event for a watched key', external.affects(E({ type: 'storage', key: W, storageArea: LS }, LS), watch))
  check('X1 other key ignored', !external.affects(E({ type: 'storage', key: 'suryadhana.prefs.meta', storageArea: LS }, LS), watch))
  check('X1 sessionStorage events ignored', E({ type: 'storage', key: W, storageArea: SS }, LS) === null)
  check('X1 clear() in another window (key null) touches every key', external.affects(E({ type: 'storage', key: null, storageArea: LS }, LS), watch))
  check('X1 storage blocked here: events still matched by key', external.affects(E({ type: 'storage', key: W, storageArea: LS }, null), watch))
  check('X1 prefs-changed {keys}', external.affects(E({ type: sync.PREFS_CHANGED_EVENT, detail: { keys: ['x', W] } }, LS), watch))
  check('X1 prefs-changed for other keys', !external.affects(E({ type: sync.PREFS_CHANGED_EVENT, detail: { keys: ['x'] } }, LS), watch))
  check('X1 malformed prefs-changed ignored', E({ type: sync.PREFS_CHANGED_EVENT, detail: null }, LS) === null && E({ type: sync.PREFS_CHANGED_EVENT, detail: { keys: 'w' } }, LS) === null)
  check('X1 unrelated events ignored', E({ type: 'focus' }, LS) === null && !external.affects(null, watch))
  // every SYNC-key consumer that caches its key adopts external changes (source guard; see useExternalChange.ts)
  const uiRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
  const adopters: Array<[string, string]> = [
    ['context/AppContext.tsx', 'WATCHLIST_KEY'], ['components/TradeTicket.tsx', 'KEY'], ['components/gold/GoldPreOpen.tsx', 'STORE'],
    ['components/FundamentalsScreen.tsx', 'SAVED'], ['components/Brief.tsx', "'suryadhana.whatsnew'"], ['lib/pins.ts', 'PIN_KEY'],
  ]
  for (const [file, key] of adopters) {
    const src = fs.readFileSync(path.join(uiRoot, file), 'utf8')
    check(`X2 ${file} adopts external changes of its key`, src.includes(`useExternalPrefChange(${key}`) || src.includes(`useExternalPrefChange([${key}`), file)
  }
  // X3 — the hook's core (subscribeExternalPrefChange): coalescing, filtering, error isolation, listener lifetime
  {
    const target = new EventTarget()
    const queue: Array<() => void> = []
    const flush = () => { while (queue.length) queue.shift()!() }
    let calls = 0
    const fire = (type: string, init: Record<string, unknown>) => { const ev = new Event(type); Object.assign(ev, init); target.dispatchEvent(ev) }
    const off = external.subscribeExternalPrefChange(target, watch, () => { calls++ }, LS, (fn) => queue.push(fn))
    // the engine applies one server value: a synthetic storage event AND prefs-changed → ONE call
    fire('storage', { key: W, storageArea: LS })
    fire(sync.PREFS_CHANGED_EVENT, { detail: { keys: [W] } })
    flush()
    check('X3 storage + prefs-changed for one change coalesce into one call', calls === 1, calls)
    fire('storage', { key: 'suryadhana.prefs.meta', storageArea: LS })
    fire('storage', { key: W, storageArea: SS })
    flush()
    check('X3 other keys and sessionStorage ignored', calls === 1, calls)
    fire('storage', { key: null, storageArea: LS })
    flush()
    check('X3 clear() in another window counts', calls === 2, calls)
    fire('storage', { key: W, storageArea: LS })
    off()
    flush()
    check('X3 a call queued before unsubscribe is dropped', calls === 2, calls)
    fire('storage', { key: W, storageArea: LS })
    flush()
    check('X3 unsubscribed: no more calls', calls === 2 && queue.length === 0, calls)
    let other = 0
    const t2 = new EventTarget()
    const offA = external.subscribeExternalPrefChange(t2, watch, () => { throw new Error('consumer bug') }, LS, (fn) => queue.push(fn))
    const offB = external.subscribeExternalPrefChange(t2, watch, () => { other++ }, LS, (fn) => queue.push(fn))
    const ev = new Event('storage'); Object.assign(ev, { key: W, storageArea: LS }); t2.dispatchEvent(ev)
    let threw = false
    try { flush() } catch { threw = true }
    check('X3 a throwing consumer never breaks the others', !threw && other === 1, other)
    offA(); offB()
    const hook = fs.readFileSync(path.join(uiRoot, 'lib/prefs/useExternalChange.ts'), 'utf8')
    check('X3 the hook delegates to subscribeExternalPrefChange', /return subscribeExternalPrefChange\(window, list\.split\('\\n'\), \(\) => cb\.current\(\), area\)/.test(hook))
  }
}

// ── 5. migration notice rule (C3-01, UI side) ──────────────────────────────────────────────────
{
  const M = migration
  check('M1 legacy browser origin = port 3000', M.isLegacyBrowserOrigin('http://localhost:3000') && M.isLegacyBrowserOrigin('http://192.168.1.20:3000')
    && !M.isLegacyBrowserOrigin('http://127.0.0.1:8010') && !M.isLegacyBrowserOrigin('tauri://localhost') && !M.isLegacyBrowserOrigin(null) && !M.isLegacyBrowserOrigin('x'))
  const rec = (o: unknown) => ({ value: '[]', updated_at: 1, deleted: false, ...(o as object) })
  const empty = M.summarizeServerPrefs({})
  check('M2 empty store', empty.live === 0 && empty.legacyOrigins.length === 0)
  const appOnly = M.summarizeServerPrefs({ [W]: rec({ provisional: true, origin: 'http://127.0.0.1:8010' }), x: rec({ provisional: false, origin: 'http://127.0.0.1:8010' }) })
  check('M2 app-only records: no legacy import', appOnly.live === 2 && appOnly.described === 2 && appOnly.legacyOrigins.length === 0, appOnly)
  const provisional3000 = M.summarizeServerPrefs({ [W]: rec({ provisional: true, origin: 'http://localhost:3000' }) })
  check('M2 a provisional :3000 default is not an import', provisional3000.legacyOrigins.length === 0)
  const migrated = M.summarizeServerPrefs({ [W]: rec({ provisional: false, origin: 'http://localhost:3000' }), d: rec({ deleted: true, provisional: false, origin: 'http://localhost:3000' }) })
  check('M2 non-provisional :3000 record = imported', migrated.legacyOrigins.join() === 'http://localhost:3000' && migrated.live === 1, migrated)
  const oldApi = M.summarizeServerPrefs({ [W]: { value: '[]', updated_at: 1, deleted: false } })
  check('M2 a ui-api without provenance: live but undescribed', oldApi.live === 1 && oldApi.described === 0)
  check('M2 garbage tolerated', M.summarizeServerPrefs(null).live === 0 && M.summarizeServerPrefs([1]).live === 0 && M.summarizeServerPrefs({ a: 5, b: null }).live === 0)
  const st = (o: Partial<import('../prefs/migration').MigrationNoticeInput>) =>
    M.migrationNoticeState({ pageOrigin: 'http://127.0.0.1:8010', mode: 'sync', marker: null, server: empty, ...o })
  // without K2 there is no proof either way: the conditional wording ('maybe'), never the claim 'not imported'
  check('M3 app origin, nothing provably imported, no K2 -> maybe', st({}) === 'maybe' && st({ server: appOnly }) === 'maybe' && st({ server: provisional3000 }) === 'maybe')
  check('M3 readonly (QA against live) still shows it', st({ mode: 'readonly' }) === 'maybe')
  check('M3 imported -> imported (marker set by the caller)', st({ server: migrated }) === 'imported')
  check('M3 old ui-api without provenance -> maybe until dismissed', st({ server: oldApi }) === 'maybe')
  // K2: GET /api/prefs `migration` = the durable answer (set on the first legacy import, never cleared)
  const k2none = M.summarizeServerPrefs({ [W]: rec({ provisional: true, origin: 'http://127.0.0.1:8010' }) },
    { legacy_import_at: null, legacy_origin: null, legacy_keys: 0 })
  const k2done = M.summarizeServerPrefs({ [W]: rec({ provisional: false, origin: 'http://127.0.0.1:8010' }) },
    { legacy_import_at: 1761369000, legacy_origin: 'http://localhost:3000', legacy_keys: 7 })
  check('K2 parsed', k2done.legacyImport?.at === 1761369000 && k2done.legacyImport?.origin === 'http://localhost:3000' && k2done.legacyImport?.keys === 7, k2done)
  check('K2 none: the server PROVES nothing was imported -> show (the factual wording)', st({ server: k2none }) === 'show')
  check('K2 import recorded -> imported even after later :8010 edits rewrote every record origin', st({ server: k2done }) === 'imported')
  check('K2 absent / malformed -> no K2 evidence', M.parseLegacyImport(undefined) === null && M.parseLegacyImport({}) === null
    && M.parseLegacyImport({ legacy_import_at: 'yesterday' }) === null && M.parseLegacyImport([1]) === null)
  check('K2 per-record legacy origin still wins when K2 says none (pre-K2 import)',
    st({ server: { ...migrated, legacyImport: { at: null, origin: null, keys: 0 } } }) === 'imported')
  check('M3 never on the old browser origin', st({ pageOrigin: 'http://localhost:3000' }) === 'hide')
  check('M3 never with sync off / server unread', st({ mode: 'off' }) === 'hide' && st({ server: null }) === 'hide')
  check('M3 dismissed / imported marker -> hidden for good', st({ marker: 'dismissed' }) === 'hide' && st({ marker: 'imported', server: appOnly }) === 'hide')
  check('M4 notice text (owner-facing wording)', M.MIGRATE_NOTICE_TEXT.includes('http://localhost:3000') && M.MIGRATE_NOTICE_TEXT.startsWith('Your watchlist and pins'))
  check('M4 the factual "not imported yet" wording only for show; maybe is conditional',
    M.migrationNoticeText('show') === M.MIGRATE_NOTICE_TEXT && M.migrationNoticeText('maybe') === M.MIGRATE_NOTICE_TEXT_MAYBE
    && !/not been imported/.test(M.MIGRATE_NOTICE_TEXT_MAYBE) && M.MIGRATE_NOTICE_TEXT_MAYBE.startsWith('If ')
    && M.MIGRATE_NOTICE_TEXT_MAYBE.includes('http://localhost:3000') && M.migrationNoticeText('hide') === '' && M.migrationNoticeText('imported') === '')
  check('M4 marker key is classified LOCAL', keys.classifyKey(M.MIGRATE_NOTICE_KEY) === 'local')
}

// ── 6. engine reports server provenance; two windows on one origin keep both edits (C3-02) ─────
{
  // A shared localStorage area with one view per window: a write through one view is delivered to every OTHER
  // window as a native 'storage' event (what browsers do); the writer's own window never sees it.
  class Area {
    m = new Map<string, string>()
    windows: Array<{ id: string; onStorage: (key: string | null) => void }> = []
    view(id: string) {
      const area = this
      const notify = (k: string) => queueMicrotask(() => area.windows.filter((w) => w.id !== id).forEach((w) => w.onStorage(k)))
      return {
        getItem: (k: string) => (area.m.has(k) ? area.m.get(k)! : null),
        setItem: (k: string, v: string) => {
          if (area.m.get(k) === v) return // the spec: an unchanged setItem is a no-op (no event)
          area.m.set(k, String(v))
          notify(k)
        },
        removeItem: (k: string) => {
          if (!area.m.has(k)) return
          area.m.delete(k)
          notify(k)
        },
      }
    }
  }
  /** The window side: a sync engine plus a watchlist consumer that caches the list (AppContext's pattern). */
  function makeAppWindow(server: FakeServer, clock: Clock, area: Area, id: string, adopt: boolean) {
    const view = area.view(id)
    const infos: unknown[] = []
    const bodies: unknown[] = []
    let consumer: { onExternal: () => void } = { onExternal: () => {} }
    const engine = new sync.PrefsSyncEngine({
      storage: view, fetch: server.fetch, apiBase: '', origin: 'http://127.0.0.1:8010',
      now: () => clock.now, setTimer: clock.set, clearTimer: clock.clear,
      onApplied: () => consumer.onExternal(), // the synthetic storage + prefs-changed in this window
      onServer: (raw, body) => { infos.push(raw); bodies.push(body) },
    })
    engine.snapshotLegacy()
    let list: string[] = []
    let stored: string | null = null
    const read = () => { try { const v = JSON.parse(view.getItem(W) || '[]'); return Array.isArray(v) ? v as string[] : null } catch { return null } }
    const persist = () => {
      const s = JSON.stringify(list)
      if (s === stored) return
      const old = view.getItem(W)
      view.setItem(W, s)
      stored = s
      if (old !== s) engine.noteLocalChange(W)
    }
    consumer = {
      onExternal: () => {
        if (!adopt) return
        const next = read()
        if (!next) return
        list = next
        stored = JSON.stringify(next)
      },
    }
    area.windows.push({ id, onStorage: (k) => { if (k === W || k === null) consumer.onExternal() } })
    return {
      engine, infos, bodies,
      mount: () => { list = read() ?? []; stored = JSON.stringify(list) },
      add: (t: string) => { if (!list.includes(t)) list = [...list, t]; persist() },
      remove: (t: string) => { list = list.filter((x) => x !== t); persist() },
      list: () => list,
    }
  }

  async function scenario(adopt: boolean) {
    const server = new FakeServer()
    const clock = new Clock()
    server.recs[W] = { value: '["RELIANCE","TCS","INFY"]', updated_at: 1000, deleted: false }
    const area = new Area()
    const w1 = makeAppWindow(server, clock, area, 'w1', adopt)
    const w2 = makeAppWindow(server, clock, area, 'w2', adopt)
    for (const w of [w1, w2]) {
      const h = await w.engine.hydrate({ timeoutMs: 1500, emit: false })
      await h.importDone
      w.mount()
    }
    clock.now += 1000
    w1.add('HDFCBANK') // window 1: add a stock
    await clock.advance(2500)
    clock.now += 1000
    w2.remove('INFY') // window 2: remove a different one, later
    await clock.advance(2500)
    await w1.engine.refetch(true)
    await clock.advance(2500)
    return { server, area, w1, w2 }
  }

  const bad = await scenario(false)
  check('E20 reproduces C3-02 without adoption (window 1 edit lost)', bad.server.recs[W].value === '["RELIANCE","TCS"]', bad.server.recs[W])
  const good = await scenario(true)
  const want = '["RELIANCE","TCS","HDFCBANK"]'
  check('E20 with adoption: the server keeps both edits', good.server.recs[W].value === want, good.server.recs[W])
  check('E20 with adoption: localStorage keeps both edits', good.area.m.get(W) === want, good.area.m.get(W))
  check('E20 with adoption: both windows show both edits', JSON.stringify(good.w1.list()) === want && JSON.stringify(good.w2.list()) === want, [good.w1.list(), good.w2.list()])
  const before = good.server.log.length
  await good.w1.engine.refetch(true)
  await good.w2.engine.refetch(true)
  check('E20 quiescent: refetches cause no writes (no ping-pong)', good.server.log.slice(before).every((l) => l.startsWith('GET')), good.server.log.slice(before))
  check('E21 onServer receives the raw prefs of every GET', good.w1.infos.length >= 2 && !!(good.w1.infos[0] as Record<string, unknown>)[W])
  check('E21 onServer also receives the whole body (top-level K2 migration provenance)',
    good.w1.bodies.length === good.w1.infos.length && (good.w1.bodies[0] as Record<string, unknown>)?.prefs === good.w1.infos[0])
}

if (failed) {
  console.error(`prefs.check: ${failed} failed, ${passed} passed`)
  process.exit(1)
}
console.log(`prefs.check: all ${passed} checks pass`)
