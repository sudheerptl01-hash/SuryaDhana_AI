/**
 * Prefs sync: localStorage <-> ui-api /api/prefs (routers/prefs.py), per-key last-write-wins.
 *
 * Why: localStorage is per origin, so the desktop app (http://127.0.0.1:8010), the old browser
 * terminal (:3000) and every other browser each had their own watchlist/pins. The SYNC keys
 * (keys.ts) now live on ui-api; localStorage stays the synchronous read path every component
 * already uses, so no component changes.
 *
 * Flow
 *  - hydratePrefs (awaited by bootstrapPlatform BEFORE the app renders, bounded by a timeout):
 *    GET /api/prefs -> planHydration (merge.ts) -> server-newer values written into localStorage,
 *    local-newer keys queued for upload, legacy keys (no meta, absent on the server) offered to the
 *    fill-only POST /api/prefs/import (the one-time migration from the old origin).
 *  - write-through: Storage.prototype.setItem/removeItem are wrapped; ONLY calls on
 *    window.localStorage for SYNC keys are observed (sessionStorage and every other key are passed
 *    straight through, untouched). A real change marks the key dirty (persisted, so it survives
 *    reloads/offline) and schedules a debounced (300 ms, max 2 s) flush: PUT/DELETE per key,
 *    retried with exponential backoff; flushed with fetch keepalive on pagehide / hidden.
 *  - on window focus (and when back online) the server is re-read and newer values applied, then
 *    'suryadhana:prefs-changed' {keys} and a synthetic 'storage' event per key are dispatched so
 *    listeners (lib/pins.ts) refresh exactly as they do for another tab's change.
 *
 * Invariants
 *  - never throws into callers (every entry point is try/catch-wrapped; QuotaExceeded from the
 *    real setItem still propagates exactly as before, the callers already catch it);
 *  - never loops: server values are applied with the ORIGINAL Storage methods, so they are not
 *    observed; native cross-window 'storage' events are not listened to at all, so two windows of
 *    the same origin cannot ping-pong (they share localStorage; the writer's window uploads once,
 *    and identical replays from a second window are idempotent on the server);
 *  - a device that never synced a key cannot overwrite the server's copy (see merge.ts): legacy
 *    values go up through the fill-only LEGACY import, other never-synced values through the
 *    PROVISIONAL import, and whenever the server's copy replaces an unsynced local value the local
 *    one is kept in 'suryadhana.prefs.backup' (recoverable, never synced).
 *
 * Modes ('suryadhana.prefs.mode' in localStorage): absent = sync; 'readonly' = hydrate from the
 * server but never write to it (QA audits against the live ui-api); 'off' = no sync at all.
 */
import { hashValue, nextStamp, planHydration, sanitizeServerPrefs, type ApplyAction, type ServerRecord } from './merge'
import {
  PREFS_BACKUP_KEY,
  PREFS_DIRTY_KEY,
  PREFS_HASH_KEY,
  PREFS_LEGACY_KEY,
  PREFS_META_KEY,
  PREFS_MODE_KEY,
  SYNC_KEYS,
  isSyncKey,
} from './keys'
import { summarizeServerPrefs, type ServerProvenance } from './migration'

export const PREFS_CHANGED_EVENT = 'suryadhana:prefs-changed'
/** Dispatched on window after every successful GET /api/prefs, detail = ServerProvenance (migration notice). */
export const PREFS_SERVER_EVENT = 'suryadhana:prefs-server'

export interface PrefsChangedDetail {
  keys: string[]
}

export const DEBOUNCE_MS = 300
export const MAX_WAIT_MS = 2000
const REQUEST_TIMEOUT_MS = 10_000
const REFETCH_MIN_INTERVAL_MS = 3000
const UNSUPPORTED_BACKOFF_MS = 5 * 60_000
const MAX_BACKOFF_MS = 60_000
const KEEPALIVE_BUDGET_BYTES = 60_000

/** The subset of Storage the engine needs (window.localStorage, or a fake in tests). */
export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

/** The subset of Response the engine reads. */
export interface ResponseLike {
  ok: boolean
  status: number
  json(): Promise<unknown>
}

export type FetchLike = (url: string, init?: RequestInit) => Promise<ResponseLike>

export interface EngineDeps {
  /** Raw (unobserved) access to the storage being synced. */
  storage: StorageLike
  fetch: FetchLike
  apiBase: string
  origin: string
  keys?: readonly string[]
  now?: () => number
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (h: unknown) => void
  /** Called after server values were applied locally (not during boot hydration). */
  onApplied?: (changes: Array<{ key: string; oldValue: string | null; newValue: string | null }>) => void
  /**
   * Called with the raw `prefs` object of every successful GET /api/prefs (boot and refetch; every mode but off),
   * plus the whole raw body (top-level `migration` provenance, contract K2).
   */
  onServer?: (rawPrefs: unknown, body?: Record<string, unknown>) => void
  warn?: (msg: string) => void
}

export type HydrateResult = 'ok' | 'timeout' | 'error' | 'unsupported' | 'off'

export type SyncMode = 'sync' | 'readonly' | 'off'

export interface SyncStatus {
  mode: SyncMode
  supported: boolean
  lastSyncAt: number | null
  pending: number
  lastError: string | null
}

type NumMap = Record<string, number>
type StrMap = Record<string, string>

function parseMap<T extends number | string>(raw: string | null, kind: 'number' | 'string'): Record<string, T> {
  if (!raw) return {}
  try {
    const o = JSON.parse(raw)
    if (!o || typeof o !== 'object' || Array.isArray(o)) return {}
    const out: Record<string, T> = {}
    for (const [k, v] of Object.entries(o)) if (typeof v === kind) out[k] = v as T
    return out
  } catch {
    return {}
  }
}

type ResolvedDeps = Required<Omit<EngineDeps, 'onApplied' | 'onServer'>> & Pick<EngineDeps, 'onApplied' | 'onServer'>

/** One engine per page (window); several windows of one origin each run their own. */
export class PrefsSyncEngine {
  private readonly d: ResolvedDeps
  private flushTimer: unknown = null
  private retryTimer: unknown = null
  private firstPendingAt = 0
  private flushing = false
  private flushAgain = false
  private attempt = 0
  private unsupportedUntil = 0
  private lastRefetchAt = 0
  private refetching: Promise<HydrateResult> | null = null
  private importRejected = new Set<string>()
  private status: SyncStatus = { mode: 'sync', supported: true, lastSyncAt: null, pending: 0, lastError: null }

  constructor(deps: EngineDeps) {
    this.d = {
      keys: deps.keys ?? SYNC_KEYS,
      now: deps.now ?? (() => Date.now()),
      setTimer: deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms)),
      clearTimer: deps.clearTimer ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>)),
      warn: deps.warn ?? (() => {}),
      storage: deps.storage,
      fetch: deps.fetch,
      apiBase: deps.apiBase,
      origin: deps.origin,
      onApplied: deps.onApplied,
      onServer: deps.onServer,
    }
  }

  // ── bookkeeping (always read fresh: other windows share this storage) ──────────────────────
  private get(key: string): string | null {
    try {
      return this.d.storage.getItem(key)
    } catch {
      return null
    }
  }
  private put(key: string, value: string): void {
    try {
      this.d.storage.setItem(key, value)
    } catch {
      /* quota / blocked: bookkeeping is best-effort */
    }
  }
  private meta(): NumMap {
    return parseMap<number>(this.get(PREFS_META_KEY), 'number')
  }
  private hashes(): StrMap {
    return parseMap<string>(this.get(PREFS_HASH_KEY), 'string')
  }
  private dirty(): NumMap {
    return parseMap<number>(this.get(PREFS_DIRTY_KEY), 'number')
  }
  private update<T>(key: string, kind: 'number' | 'string', fn: (m: Record<string, T>) => void): void {
    const m = parseMap<T & (number | string)>(this.get(key), kind) as Record<string, T>
    fn(m)
    this.put(key, JSON.stringify(m))
  }
  private markSynced(key: string, updatedAt: number, value: string | null): void {
    this.update<number>(PREFS_META_KEY, 'number', (m) => {
      m[key] = updatedAt
    })
    this.update<string>(PREFS_HASH_KEY, 'string', (m) => {
      m[key] = hashValue(value)
    })
  }
  private clearDirty(key: string, onlyIf?: number): void {
    this.update<number>(PREFS_DIRTY_KEY, 'number', (m) => {
      if (onlyIf === undefined || m[key] === onlyIf) delete m[key]
    })
  }
  private warn(msg: string): void {
    this.status.lastError = msg
    try {
      this.d.warn(msg)
    } catch {
      /* ignore */
    }
  }

  /** 'readonly' / 'off' from localStorage 'suryadhana.prefs.mode' (read fresh: tests and QA set it). */
  mode(): SyncMode {
    const m = this.get(PREFS_MODE_KEY)
    return m === 'off' || m === 'readonly' ? m : 'sync'
  }

  /** Public status for diagnostics / a sync indicator. */
  getStatus(): SyncStatus {
    return { ...this.status, mode: this.mode(), pending: Object.keys(this.dirty()).length }
  }

  /** Keep the first unsynced local value a server copy replaced (bounded, best-effort, never synced). */
  private backup(key: string, value: string | null, replacement: string | null): void {
    if (value === null || value === replacement || value.length > 262_144) return
    try {
      const raw = this.get(PREFS_BACKUP_KEY)
      const m = raw ? (JSON.parse(raw) as Record<string, { value: string; at: number }>) : {}
      if (!m || typeof m !== 'object' || m[key]) return
      m[key] = { value, at: this.d.now() }
      this.put(PREFS_BACKUP_KEY, JSON.stringify(m))
    } catch {
      /* best-effort */
    }
  }

  /**
   * Record which SYNC keys already hold a value before the sync code first runs on this origin.
   * Called when the page engine is created (before the write-through is installed and before the
   * app renders); idempotent — later calls never change an existing snapshot.
   */
  snapshotLegacy(): void {
    try {
      this.legacyKeys()
    } catch {
      /* best-effort */
    }
  }

  /** The legacy snapshot (taken now if it does not exist yet). */
  private legacyKeys(): string[] {
    const raw = this.get(PREFS_LEGACY_KEY)
    if (raw === null) {
      const first = this.get(PREFS_META_KEY) === null
      const legacy = first ? this.d.keys.filter((k) => this.get(k) !== null) : []
      this.put(PREFS_LEGACY_KEY, JSON.stringify(legacy))
      return legacy
    }
    try {
      const a = JSON.parse(raw)
      return Array.isArray(a) ? a.filter((k): k is string => typeof k === 'string') : []
    } catch {
      return []
    }
  }

  private url(key?: string): string {
    return `${this.d.apiBase}/api/prefs${key ? `/${encodeURIComponent(key)}` : ''}`
  }

  private async request(url: string, init: RequestInit, timeoutMs: number): Promise<ResponseLike> {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null
    const h = ctrl ? this.d.setTimer(() => ctrl.abort(), timeoutMs) : null
    try {
      return await this.d.fetch(url, { ...init, signal: ctrl?.signal, credentials: 'same-origin', cache: 'no-store' })
    } finally {
      if (h != null) this.d.clearTimer(h)
    }
  }

  // ── local changes (called by the Storage wrapper) ──────────────────────────────────────────

  /** A SYNC key's value really changed locally: mark it dirty and schedule a flush. Never throws. */
  noteLocalChange(key: string): void {
    try {
      if (!isSyncKey(key) || !this.d.keys.includes(key) || this.mode() !== 'sync') return
      const t = this.meta()[key]
      this.update<number>(PREFS_DIRTY_KEY, 'number', (m) => {
        m[key] = nextStamp(this.d.now(), t, m[key])
      })
      this.scheduleFlush()
    } catch (e) {
      this.warn(`prefs: could not queue ${key}: ${e instanceof Error ? e.message : e}`)
    }
  }

  scheduleFlush(delay = DEBOUNCE_MS): void {
    const now = this.d.now()
    if (!this.firstPendingAt) this.firstPendingAt = now
    const wait = Math.max(0, Math.min(delay, this.firstPendingAt + MAX_WAIT_MS - now))
    if (this.flushTimer != null) this.d.clearTimer(this.flushTimer)
    this.flushTimer = this.d.setTimer(() => {
      this.flushTimer = null
      void this.flush()
    }, wait)
  }

  private scheduleRetry(): void {
    if (this.retryTimer != null) return
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(this.attempt, 6))
    const delay = Math.round(base * (0.8 + Math.random() * 0.4))
    this.attempt++
    this.retryTimer = this.d.setTimer(() => {
      this.retryTimer = null
      void this.flush()
    }, delay)
  }

  /** Upload every dirty SYNC key that has been synced at least once. Never rejects. */
  async flush(opts: { keepalive?: boolean } = {}): Promise<void> {
    if (this.flushing) {
      this.flushAgain = true
      return
    }
    if (this.d.now() < this.unsupportedUntil || this.mode() !== 'sync') return
    this.flushing = true
    this.firstPendingAt = 0
    let retry = false
    let reconcile = false
    try {
      const dirty = this.dirty()
      const meta = this.meta()
      const hashes = this.hashes()
      let keepaliveBudget = KEEPALIVE_BUDGET_BYTES
      const jobs: Array<Promise<void>> = []
      for (const [key, d] of Object.entries(dirty)) {
        if (!isSyncKey(key) || !this.d.keys.includes(key)) {
          this.clearDirty(key)
          continue
        }
        const t = meta[key]
        if (t === undefined) {
          // Never synced here: only hydration may decide (fill-only import or adopt the server copy).
          if (!this.importRejected.has(key)) reconcile = true
          continue
        }
        const v = this.get(key)
        if (d < t || (d > t && hashValue(v) === hashes[key])) {
          this.clearDirty(key, d) // transient change that ended where it started, or stale
          continue
        }
        let init: RequestInit
        let url: string
        if (v === null) {
          url = `${this.url(key)}?updated_at=${d}`
          init = { method: 'DELETE' }
        } else {
          url = this.url(key)
          const body = JSON.stringify({ value: v, updated_at: d, origin: this.d.origin })
          init = { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body }
        }
        if (opts.keepalive) {
          const size = typeof init.body === 'string' ? init.body.length + 256 : 256
          if (size <= keepaliveBudget) {
            init.keepalive = true
            keepaliveBudget -= size
          }
        }
        jobs.push(
          this.sendOne(key, d, v, url, init).then((r) => {
            if (r === 'retry') retry = true
          }),
        )
      }
      await Promise.all(jobs)
    } catch (e) {
      retry = true
      this.warn(`prefs: flush failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      this.flushing = false
    }
    if (retry) this.scheduleRetry()
    else this.attempt = 0
    if (reconcile) void this.refetch(true) // single-flight; after it those keys have meta or are clean
    if (this.flushAgain) {
      this.flushAgain = false
      this.scheduleFlush(0)
    }
  }

  private async sendOne(key: string, d: number, sent: string | null, url: string, init: RequestInit): Promise<'done' | 'retry'> {
    let res: ResponseLike
    try {
      res = await this.request(url, init, REQUEST_TIMEOUT_MS)
    } catch {
      this.status.lastError = 'prefs: server unreachable'
      return 'retry'
    }
    let body: Record<string, unknown> = {}
    try {
      body = ((await res.json()) as Record<string, unknown>) || {}
    } catch {
      /* non-JSON */
    }
    if (res.ok) {
      const rec = sanitizeServerPrefs({ [key]: body.pref })[key]
      this.markSynced(key, rec ? rec.updated_at : d, sent)
      this.clearDirty(key, d)
      this.status.lastSyncAt = this.d.now()
      this.status.supported = true
      return 'done'
    }
    if (res.status === 409) {
      const cur = sanitizeServerPrefs({ [key]: body.current })[key]
      // Server holds a newer state: adopt it unless the user changed the key again meanwhile.
      if (cur && this.dirty()[key] === d) this.applyRecords([{ key, value: cur.deleted ? null : cur.value, updated_at: cur.updated_at }], true)
      return 'done'
    }
    if (res.status === 404) {
      this.markUnsupported()
      return 'done'
    }
    if (res.status === 400 || res.status === 413 || res.status === 422) {
      this.clearDirty(key, d) // can never succeed: the value stays local only
      this.warn(`prefs: server refused ${key} (HTTP ${res.status}); kept locally`)
      return 'done'
    }
    this.status.lastError = `prefs: HTTP ${res.status}`
    return 'retry'
  }

  private markUnsupported(): void {
    this.unsupportedUntil = this.d.now() + UNSUPPORTED_BACKOFF_MS
    if (this.status.supported) this.warn('prefs: this ui-api has no /api/prefs yet; settings stay local')
    this.status.supported = false
  }

  /** Write server state into storage with the raw methods (never observed, never re-uploaded). */
  private applyRecords(actions: ApplyAction[], emit: boolean): string[] {
    const changes: Array<{ key: string; oldValue: string | null; newValue: string | null }> = []
    for (const a of actions) {
      try {
        const old = this.get(a.key)
        if (a.value === null) {
          if (old !== null) this.d.storage.removeItem(a.key)
        } else if (old !== a.value) {
          this.d.storage.setItem(a.key, a.value)
        }
        this.markSynced(a.key, a.updated_at, a.value)
        this.clearDirty(a.key)
        if (old !== a.value) changes.push({ key: a.key, oldValue: old, newValue: a.value })
      } catch (e) {
        this.warn(`prefs: could not apply ${a.key}: ${e instanceof Error ? e.message : e}`)
      }
    }
    if (emit && changes.length && this.d.onApplied) {
      try {
        this.d.onApplied(changes)
      } catch {
        /* listener errors are not ours */
      }
    }
    return changes.map((c) => c.key)
  }

  // ── hydration ──────────────────────────────────────────────────────────────────────────────

  /**
   * Read the server, apply server-newer values, queue local-newer uploads and start the legacy
   * import. Resolves within `timeoutMs` for the GET; the import continues in the background and
   * is exposed as `importDone` (boot awaits it only for the remaining budget).
   */
  async hydrate(opts: { timeoutMs: number; emit: boolean }): Promise<{ result: HydrateResult; importDone: Promise<void> }> {
    const none = Promise.resolve()
    const mode = this.mode()
    if (mode === 'off') return { result: 'off', importDone: none }
    const legacy = this.legacyKeys() // before the GET: the app has not rendered yet
    if (this.d.now() < this.unsupportedUntil) return { result: 'unsupported', importDone: none }
    let res: ResponseLike
    let body: Record<string, unknown>
    try {
      res = await this.request(this.url(), { method: 'GET' }, opts.timeoutMs)
      if (res.status === 404) {
        this.markUnsupported()
        return { result: 'unsupported', importDone: none }
      }
      if (!res.ok) {
        this.status.lastError = `prefs: HTTP ${res.status}`
        return { result: 'error', importDone: none }
      }
      body = ((await res.json()) as Record<string, unknown>) || {}
    } catch (e) {
      const aborted = !!e && typeof e === 'object' && (e as { name?: string }).name === 'AbortError'
      this.status.lastError = aborted ? 'prefs: server timeout' : 'prefs: server unreachable'
      return { result: aborted ? 'timeout' : 'error', importDone: none }
    }
    this.status.supported = true
    this.unsupportedUntil = 0
    try {
      this.d.onServer?.(body.prefs, body)
    } catch {
      /* listener errors are not ours */
    }
    const server = sanitizeServerPrefs(body.prefs)
    const keys = this.d.keys
    const values: Record<string, string | null> = {}
    for (const k of keys) values[k] = this.get(k)
    const meta = this.meta()
    const plan = planHydration(keys, server, { values, meta, hash: this.hashes(), dirty: this.dirty(), legacy })

    for (const a of plan.apply) if (meta[a.key] === undefined) this.backup(a.key, values[a.key], a.value)
    this.applyRecords(plan.apply, opts.emit)
    this.status.lastSyncAt = this.d.now()
    if (mode === 'readonly') return { result: 'ok', importDone: none }
    for (const k of plan.clean) this.clearDirty(k)
    if (plan.upload.length) {
      this.update<number>(PREFS_DIRTY_KEY, 'number', (m) => {
        for (const u of plan.upload) if (m[u.key] === undefined || m[u.key] < u.updated_at) m[u.key] = u.updated_at
      })
      this.scheduleFlush(0)
    }
    const pick = (src: Record<string, string>) => {
      const out: Record<string, string> = {}
      for (const [k, v] of Object.entries(src)) if (!this.importRejected.has(k)) out[k] = v
      return out
    }
    const legacyItems = pick(plan.imports)
    const provisionalItems = pick(plan.provisional)
    const importDone = (async () => {
      if (Object.keys(legacyItems).length) await this.runImport(legacyItems, opts.emit, false)
      if (Object.keys(provisionalItems).length) await this.runImport(provisionalItems, opts.emit, true)
    })()
    return { result: 'ok', importDone }
  }

  /** Fill-only import; `provisional` marks never-synced defaults that a legacy import may replace. */
  private async runImport(items: Record<string, string>, emit: boolean, provisional: boolean): Promise<void> {
    let res: ResponseLike
    let body: Record<string, unknown> = {}
    try {
      res = await this.request(
        `${this.url()}/import`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items, origin: this.d.origin, provisional }) },
        REQUEST_TIMEOUT_MS,
      )
      body = ((await res.json()) as Record<string, unknown>) || {}
    } catch {
      this.status.lastError = 'prefs: import failed (will retry on next sync)'
      return
    }
    if (!res.ok) {
      if (res.status === 404) this.markUnsupported()
      else this.status.lastError = `prefs: import HTTP ${res.status}`
      return
    }
    const recs = sanitizeServerPrefs(body.prefs)
    const imported = Array.isArray(body.imported) ? (body.imported as unknown[]).filter((k): k is string => typeof k === 'string') : []
    const skipped = Array.isArray(body.skipped) ? (body.skipped as unknown[]).filter((k): k is string => typeof k === 'string') : []
    const rejected = body.rejected && typeof body.rejected === 'object' ? Object.keys(body.rejected as object) : []
    for (const k of imported) {
      const rec: ServerRecord | undefined = recs[k]
      if (!rec || !(k in items)) continue
      this.markSynced(k, rec.updated_at, items[k])
      // Edited while the import was in flight: make sure the edit wins over the imported copy.
      if (this.get(k) === items[k]) this.clearDirty(k)
      else {
        this.update<number>(PREFS_DIRTY_KEY, 'number', (m) => {
          m[k] = Math.max(m[k] ?? 0, rec.updated_at + 1)
        })
        this.scheduleFlush(0)
      }
    }
    const adopt: ApplyAction[] = []
    for (const k of skipped) {
      const rec = recs[k]
      if (!rec) continue
      const value = rec.deleted ? null : rec.value
      if (this.get(k) !== items[k]) {
        // Edited while the import was in flight: a deliberate change after the server copy -> plain LWW.
        this.markSynced(k, rec.updated_at, value)
        this.update<number>(PREFS_DIRTY_KEY, 'number', (m) => {
          m[k] = Math.max(m[k] ?? 0, rec.updated_at + 1)
        })
        this.scheduleFlush(0)
        continue
      }
      this.backup(k, items[k], value) // the server's real copy wins; keep this device's for recovery
      adopt.push({ key: k, value, updated_at: rec.updated_at })
    }
    this.applyRecords(adopt, emit)
    for (const k of rejected) this.importRejected.add(k)
    if (rejected.length) this.warn(`prefs: server refused ${rejected.length} key(s) on import; kept locally`)
  }

  /** Re-read the server (window focus / online), throttled and single-flight. */
  refetch(force = false): Promise<HydrateResult> {
    const now = this.d.now()
    if (this.refetching) return this.refetching
    if (!force && now - this.lastRefetchAt < REFETCH_MIN_INTERVAL_MS) return Promise.resolve('ok')
    if (now < this.unsupportedUntil) return Promise.resolve('unsupported')
    this.lastRefetchAt = now
    this.refetching = (async () => {
      try {
        const { result, importDone } = await this.hydrate({ timeoutMs: REQUEST_TIMEOUT_MS, emit: true })
        await importDone
        if (result === 'ok') void this.flush()
        return result
      } catch {
        return 'error' as HydrateResult
      } finally {
        this.refetching = null
      }
    })()
    return this.refetching
  }
}

/**
 * Observe Storage writes for SYNC keys on `target` only, by wrapping `proto.setItem/removeItem`
 * (Storage is a legacy platform object: assigning or defining methods on the instance would
 * create storage items named "setItem"). The original methods are kept on the prototype, so a
 * second install (dev hot reload) only retargets the handler instead of double-wrapping.
 * Returns the uninstall function.
 */
const WRAPPED = '__suryadhanaPrefsWrap'

interface StorageProtoLike {
  setItem: (k: string, v: string) => void
  removeItem: (k: string) => void
  getItem: (k: string) => string | null
}

interface WrapState {
  orig: StorageProtoLike
  target: object
  onChange: (key: string) => void
  uninstall: () => void
}

/** The unwrapped methods of a (possibly wrapped) prototype. */
export function originalMethods(proto: StorageProtoLike): StorageProtoLike {
  const st = (proto as StorageProtoLike & { [WRAPPED]?: WrapState })[WRAPPED]
  return st ? st.orig : { setItem: proto.setItem, removeItem: proto.removeItem, getItem: proto.getItem }
}

export function installWriteThroughOn(proto: StorageProtoLike, target: object, onChange: (key: string) => void): () => void {
  const p = proto as StorageProtoLike & { [WRAPPED]?: WrapState }
  const existing = p[WRAPPED]
  if (existing) {
    existing.target = target
    existing.onChange = onChange
    return existing.uninstall
  }
  const orig: StorageProtoLike = { setItem: proto.setItem, removeItem: proto.removeItem, getItem: proto.getItem }
  const state: WrapState = { orig, target, onChange, uninstall: () => {} }
  const observed = (self: unknown, key: unknown) => self === state.target && isSyncKey(String(key))

  const setItem = function (this: unknown, ...args: [string, string]) {
    if (!observed(this, args[0])) return orig.setItem.apply(this, args)
    let old: string | null = null
    try {
      old = orig.getItem.call(this, String(args[0]))
    } catch {
      /* unreadable: treat as changed */
    }
    const r = orig.setItem.apply(this, args) // may throw QuotaExceeded exactly as before
    try {
      if (old !== String(args[1])) state.onChange(String(args[0]))
    } catch {
      /* never into callers */
    }
    return r
  }
  const removeItem = function (this: unknown, ...args: [string]) {
    if (!observed(this, args[0])) return orig.removeItem.apply(this, args)
    let old: string | null = null
    try {
      old = orig.getItem.call(this, String(args[0]))
    } catch {
      /* ignore */
    }
    const r = orig.removeItem.apply(this, args)
    try {
      if (old !== null) state.onChange(String(args[0]))
    } catch {
      /* never into callers */
    }
    return r
  }
  proto.setItem = setItem
  proto.removeItem = removeItem
  state.uninstall = () => {
    if (proto.setItem === setItem) proto.setItem = orig.setItem
    if (proto.removeItem === removeItem) proto.removeItem = orig.removeItem
    delete p[WRAPPED]
  }
  p[WRAPPED] = state
  return state.uninstall
}

// ── page singleton (browser / desktop) ───────────────────────────────────────────────────────

let engine: PrefsSyncEngine | null = null
let listenersInstalled = false
let serverInfo: ServerProvenance | null = null

function pageStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null
  } catch {
    return null // storage blocked (private mode / policy)
  }
}

/** Raw storage access through the ORIGINAL prototype methods (bypasses the observer). */
function rawStorage(ls: Storage): StorageLike {
  const orig = originalMethods(Storage.prototype)
  return {
    getItem: (k) => orig.getItem.call(ls, k),
    setItem: (k, v) => orig.setItem.call(ls, k, v),
    removeItem: (k) => orig.removeItem.call(ls, k),
  }
}

function dispatchApplied(changes: Array<{ key: string; oldValue: string | null; newValue: string | null }>): void {
  if (typeof window === 'undefined') return
  const ls = pageStorage()
  for (const c of changes) {
    try {
      window.dispatchEvent(
        new StorageEvent('storage', { key: c.key, oldValue: c.oldValue, newValue: c.newValue, storageArea: ls, url: window.location.href }),
      )
    } catch {
      /* StorageEvent unsupported */
    }
  }
  try {
    window.dispatchEvent(new CustomEvent<PrefsChangedDetail>(PREFS_CHANGED_EVENT, { detail: { keys: changes.map((c) => c.key) } }))
  } catch {
    /* ignore */
  }
}

function recordServer(rawPrefs: unknown, body?: Record<string, unknown>): void {
  serverInfo = summarizeServerPrefs(rawPrefs, body?.migration)
  try {
    window.dispatchEvent(new CustomEvent<ServerProvenance>(PREFS_SERVER_EVENT, { detail: serverInfo }))
  } catch {
    /* ignore */
  }
}

function ensureEngine(apiBase = ''): PrefsSyncEngine | null {
  if (engine) return engine
  const ls = pageStorage()
  if (!ls || typeof fetch === 'undefined') return null
  engine = new PrefsSyncEngine({
    storage: rawStorage(ls),
    fetch: (u, i) => fetch(u, i),
    apiBase,
    origin: window.location.origin,
    onApplied: dispatchApplied,
    onServer: recordServer,
    warn: (m) => {
      try {
        console.warn(`[prefs] ${m}`)
      } catch {
        /* ignore */
      }
    },
  })
  engine.snapshotLegacy() // before the observer is installed and before the app renders
  return engine
}

/** Install the write-through observer + focus/online/pagehide hooks. Idempotent; never throws. */
export function installPrefsWriteThrough(opts: { apiBase?: string } = {}): void {
  try {
    const ls = pageStorage()
    const eng = ensureEngine(opts.apiBase ?? '')
    if (!ls || !eng) return
    installWriteThroughOn(Storage.prototype, ls, (k) => eng.noteLocalChange(k))
    if (listenersInstalled) return
    listenersInstalled = true
    const onVisible = () => {
      if (document.visibilityState === 'hidden') void eng.flush({ keepalive: true })
      else void eng.refetch()
    }
    window.addEventListener('focus', () => void eng.refetch())
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('pagehide', () => void eng.flush({ keepalive: true }))
    window.addEventListener('online', () => {
      void eng.refetch(true)
      void eng.flush()
    })
  } catch (e) {
    try {
      console.warn(`[prefs] write-through unavailable: ${e instanceof Error ? e.message : e}`)
    } catch {
      /* ignore */
    }
  }
}

export interface HydrateOptions {
  /** Budget for the boot GET (+ import) before rendering anyway. Default 1500 ms. */
  timeoutMs?: number
  apiBase?: string
}

let backgroundRetry: ReturnType<typeof setTimeout> | null = null

function retryInBackground(eng: PrefsSyncEngine, attempt = 0): void {
  if (backgroundRetry) return
  const delay = Math.min(60_000, 2000 * 2 ** attempt)
  backgroundRetry = setTimeout(() => {
    backgroundRetry = null
    void eng.refetch(true).then((r) => {
      if (r === 'timeout' || r === 'error') retryInBackground(eng, attempt + 1)
    })
  }, delay)
}

/**
 * Hydrate localStorage from ui-api before the app renders. Resolves within ~timeoutMs whatever
 * happens (on timeout/error the app renders from local values and sync retries in the background).
 * Never rejects.
 */
export async function hydratePrefs(opts: HydrateOptions = {}): Promise<HydrateResult> {
  const timeoutMs = Math.max(0, opts.timeoutMs ?? 1500)
  const started = Date.now()
  try {
    const eng = ensureEngine(opts.apiBase ?? '')
    if (!eng) return 'error'
    const { result, importDone } = await eng.hydrate({ timeoutMs, emit: false })
    if (result === 'timeout' || result === 'error') retryInBackground(eng)
    const remaining = timeoutMs - (Date.now() - started)
    if (remaining > 0) await Promise.race([importDone, new Promise<void>((r) => setTimeout(r, remaining))])
    return result
  } catch {
    return 'error'
  }
}

/** Provenance summary of the last GET /api/prefs on this page (null until the server has been read). */
export function prefsServerInfo(): ServerProvenance | null {
  return serverInfo
}

/** Diagnostics for a sync indicator (null before the engine exists, e.g. during SSR). */
export function prefsSyncStatus(): SyncStatus | null {
  try {
    return engine ? engine.getStatus() : null
  } catch {
    return null
  }
}
