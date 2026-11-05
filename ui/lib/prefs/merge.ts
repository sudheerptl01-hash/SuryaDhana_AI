/**
 * Pure per-key last-write-wins planning for prefs hydration (no DOM, no I/O; unit-tested under
 * plain node by ui/lib/__tests__/prefs.check.ts).
 *
 * Local bookkeeping (all in localStorage, see keys.ts):
 *   meta[k]  = updated_at of the last state this device KNOWS is on the server (applied or uploaded)
 *   hash[k]  = hashValue() of that state's value (null = deleted)
 *   dirty[k] = updated_at to upload with. A local write sets it to max(now, prev+1) (> meta[k]);
 *              a forced re-upload (server lost / regressed the key) sets it equal to meta[k].
 *
 * Safety rule: a device that never synced a key (no meta) can never overwrite the server's copy
 * through LWW. Two cases:
 *  - LEGACY value (present in this origin's localStorage before the sync code first ran here, e.g.
 *    the old :3000 browser): always offered through the fill-only LEGACY import, even when the
 *    server has the key — the server replaces only PROVISIONAL values and otherwise answers
 *    "skipped" (the client then adopts the server copy and keeps a local backup);
 *  - any other never-synced value (a component persisting its default on first mount, e.g. the
 *    watchlist's `[]` on a fresh origin): the server copy wins; when the server lacks the key it
 *    goes up as a PROVISIONAL import, which a later legacy import still replaces.
 * That is what keeps an empty new origin (the desktop app on first launch) from wiping the owner's
 * watchlist, in whichever order the app and the old browser are opened.
 */

export interface ServerRecord {
  value: string | null
  updated_at: number
  deleted: boolean
}

export type ServerPrefs = Record<string, ServerRecord>

export interface LocalState {
  /** Current localStorage value per key (null = absent). Missing entries count as null. */
  values: Record<string, string | null>
  meta: Record<string, number>
  hash: Record<string, string>
  dirty: Record<string, number>
  /** SYNC keys that held a value before the sync code first ran on this origin. */
  legacy?: readonly string[]
}

export interface ApplyAction {
  key: string
  /** null = remove the key locally (server tombstone). */
  value: string | null
  updated_at: number
}

export interface HydrationPlan {
  /** Server state to write into localStorage (server wins). */
  apply: ApplyAction[]
  /** Keys to upload (value is read from localStorage at flush time) with this updated_at. */
  upload: Array<{ key: string; updated_at: number }>
  /** Legacy local values (never synced here) for the fill-only LEGACY import. */
  imports: Record<string, string>
  /** Other never-synced local values the server lacks, for the PROVISIONAL import. */
  provisional: Record<string, string>
  /** Keys whose dirty flag is stale (transient writes that ended where they started). */
  clean: string[]
}

/** FNV-1a 32-bit over UTF-16 code units + length; null (deleted/absent) has its own marker. */
export function hashValue(v: string | null | undefined): string {
  if (v == null) return '~'
  let h = 0x811c9dc5
  for (let i = 0; i < v.length; i++) {
    h ^= v.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return `${v.length.toString(36)}.${h.toString(36)}`
}

function recordValue(s: ServerRecord): string | null {
  return s.deleted ? null : s.value ?? null
}

function isRecord(x: unknown): x is ServerRecord {
  if (!x || typeof x !== 'object') return false
  const r = x as Record<string, unknown>
  return (
    typeof r.updated_at === 'number' &&
    Number.isFinite(r.updated_at) &&
    typeof r.deleted === 'boolean' &&
    (r.deleted ? true : typeof r.value === 'string')
  )
}

/** Keep only well-formed server records (the client never trusts payload shapes blindly). */
export function sanitizeServerPrefs(raw: unknown): ServerPrefs {
  const out: ServerPrefs = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (isRecord(v)) out[k] = { value: v.deleted ? null : (v.value as string), updated_at: v.updated_at, deleted: v.deleted }
  }
  return out
}

/**
 * Decide, per allowlisted key, whether the server or the local copy wins.
 * Only `keys` are considered; server keys outside the allowlist are ignored.
 */
export function planHydration(keys: readonly string[], server: ServerPrefs, local: LocalState): HydrationPlan {
  const plan: HydrationPlan = { apply: [], upload: [], imports: {}, provisional: {}, clean: [] }
  const legacy = new Set(local.legacy ?? [])
  for (const k of keys) {
    const s = Object.prototype.hasOwnProperty.call(server, k) ? server[k] : undefined
    const v = local.values[k] ?? null
    const t = local.meta[k]
    const d = local.dirty[k]
    const apply = (rec: ServerRecord) => plan.apply.push({ key: k, value: recordValue(rec), updated_at: rec.updated_at })

    if (t === undefined) {
      if (legacy.has(k) && v !== null) {
        plan.imports[k] = v // the server decides: fills absent/provisional, else "skipped" -> adopt
        continue
      }
      // Never synced on this device: the server copy is authoritative.
      if (s) apply(s)
      else {
        if (v !== null) plan.provisional[k] = v
        if (d !== undefined) plan.clean.push(k)
      }
      continue
    }

    const localChanged = d !== undefined && (d === t || hashValue(v) !== local.hash[k])
    if (localChanged) {
      const sameAsServer = !!s && hashValue(recordValue(s)) === hashValue(v)
      if (s && (s.updated_at > d! || (s.updated_at === d && sameAsServer))) apply(s)
      else if (!s && v === null) plan.clean.push(k) // deleted here, server never had it: nothing to do
      else plan.upload.push({ key: k, updated_at: d! })
      continue
    }
    if (d !== undefined) plan.clean.push(k) // transient change that ended where it started

    if (!s) {
      if (v !== null) plan.upload.push({ key: k, updated_at: t }) // server lost it: restore from this device
      continue
    }
    if (s.updated_at > t) apply(s)
    else if (s.updated_at < t) plan.upload.push({ key: k, updated_at: t }) // server regressed (restored backup)
  }
  return plan
}

/** Next local change stamp: strictly newer than anything known for the key, monotonic per key. */
export function nextStamp(now: number, meta?: number, dirty?: number): number {
  return Math.max(Math.floor(now), (meta ?? 0) + 1, (dirty ?? 0) + 1)
}
