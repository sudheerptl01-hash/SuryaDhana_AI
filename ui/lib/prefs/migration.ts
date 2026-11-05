/**
 * The one-time "settings not imported yet" notice (C3-01, UI side).
 *
 * localStorage is per origin, so the owner's watchlist, pins and other settings exist only in the browser that
 * ran the old terminal on http://localhost:3000 until that browser loads a build with the sync code once: its
 * legacy import (sync.ts) then puts them on ui-api, and the app and every browser hydrate them from there. Until
 * that happens the app (and the browser on :8010) start from defaults, which looks like lost data. This module
 * decides when to say so.
 *
 * Rule (pure, unit-tested by ui/lib/__tests__/prefs.check.ts):
 *  - never on the old browser origin itself (port 3000: that IS where the import runs), never with sync 'off',
 *    and never when the server could not be read (no evidence either way: no nagging);
 *  - hidden for good once the server holds a live, non-provisional record written from a port-3000 origin (the
 *    legacy import, or any later write from the old browser): the LOCAL marker is then set to 'imported', so a
 *    later edit here that rewrites those records' origin can never bring the notice back;
 *  - hidden for good once dismissed (marker 'dismissed');
 *  - the durable answer is GET /api/prefs `migration` (contract K2, routers/prefs.py): {legacy_import_at,
 *    legacy_origin, legacy_keys}, set on the FIRST legacy (non-provisional) import and never cleared. With it,
 *    `legacy_import_at` set (or any per-record legacy origin) means imported; null means the server has never
 *    received a legacy import, and only then does the notice say, as a fact, that nothing was imported;
 *  - without K2 (an older ui-api) there is no proof either way: the notice is worded as a conditional
 *    ('If you used the browser terminal before …', state 'maybe'), still shown once until dismissed: telling the
 *    owner once too often is cheaper than letting the settings look lost, but it never claims something false.
 */

/** LOCAL key (keys.ts): 'dismissed' | 'imported' once the notice should never show again on this origin. */
export const MIGRATE_NOTICE_KEY = 'suryadhana.migrate.notice.v1'

/** The old browser terminal's port (next start / next dev -p 3000). */
export const LEGACY_BROWSER_PORT = '3000'

/** Shown when the server PROVES no legacy import ever happened (K2 `migration.legacy_import_at` is null). */
export const MIGRATE_NOTICE_TEXT =
  'Your watchlist and pins from the browser terminal have not been imported yet — open http://localhost:3000 once in the browser you used.'

/** Shown when the server cannot say (no K2 provenance): a conditional, never a claim. */
export const MIGRATE_NOTICE_TEXT_MAYBE =
  'If you used the browser terminal before, open http://localhost:3000 once in that browser to bring its watchlist and pins here.'

/** GET /api/prefs `migration` (contract K2), validated. */
export interface LegacyImportInfo {
  /** Epoch (s or ms, as the server sends it) of the first legacy import, or null when none ever happened. */
  at: number | null
  origin: string | null
  keys: number
}

/** Validate the K2 block; null when absent or malformed (an older ui-api). */
export function parseLegacyImport(raw: unknown): LegacyImportInfo | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const m = raw as { legacy_import_at?: unknown; legacy_origin?: unknown; legacy_keys?: unknown }
  if (!('legacy_import_at' in m)) return null
  const at = typeof m.legacy_import_at === 'number' && Number.isFinite(m.legacy_import_at) && m.legacy_import_at > 0 ? m.legacy_import_at : null
  if (m.legacy_import_at !== null && at === null) return null
  return {
    at,
    origin: typeof m.legacy_origin === 'string' && m.legacy_origin ? m.legacy_origin : null,
    keys: typeof m.legacy_keys === 'number' && Number.isFinite(m.legacy_keys) && m.legacy_keys >= 0 ? Math.floor(m.legacy_keys) : 0,
  }
}

export interface ServerProvenance {
  /** Live (not deleted) records on the server. */
  live: number
  /** Live records that report their provenance (`provisional` and `origin`); 0 on a ui-api that predates it. */
  described: number
  /** Distinct port-3000 origins of live, non-provisional records (the legacy import and old-browser writes). */
  legacyOrigins: string[]
  /** The durable K2 answer, or null when the server does not report it. */
  legacyImport: LegacyImportInfo | null
}

export function isLegacyBrowserOrigin(origin: unknown): boolean {
  if (typeof origin !== 'string' || !origin) return false
  try {
    const u = new URL(origin)
    return (u.protocol === 'http:' || u.protocol === 'https:') && u.port === LEGACY_BROWSER_PORT
  } catch {
    return false
  }
}

/** Summarize GET /api/prefs `prefs` and its top-level `migration` (raw, unvalidated server JSON). Never throws. */
export function summarizeServerPrefs(raw: unknown, migrationRaw?: unknown): ServerProvenance {
  const out: ServerProvenance = { live: 0, described: 0, legacyOrigins: [], legacyImport: parseLegacyImport(migrationRaw) }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out
  const legacy = new Set<string>()
  for (const rec of Object.values(raw as Record<string, unknown>)) {
    if (!rec || typeof rec !== 'object') continue
    const r = rec as { deleted?: unknown; provisional?: unknown; origin?: unknown }
    if (r.deleted === true) continue
    out.live++
    if (typeof r.provisional !== 'boolean' || !('origin' in r)) continue
    out.described++
    if (!r.provisional && isLegacyBrowserOrigin(r.origin)) legacy.add(r.origin as string)
  }
  out.legacyOrigins = [...legacy].sort()
  return out
}

/**
 * 'show' = the server proves nothing was imported (MIGRATE_NOTICE_TEXT); 'maybe' = the server cannot say
 * (MIGRATE_NOTICE_TEXT_MAYBE); 'imported' = hide, and the caller records the marker so the notice never returns
 * on this origin.
 */
export type MigrationNoticeState = 'show' | 'maybe' | 'hide' | 'imported'

export interface MigrationNoticeInput {
  /** window.location.origin of this page. */
  pageOrigin: string
  mode: 'sync' | 'readonly' | 'off'
  /** localStorage[MIGRATE_NOTICE_KEY]. */
  marker: string | null
  /** The last GET /api/prefs summary, or null when the server has not been read (yet). */
  server: ServerProvenance | null
}

export function migrationNoticeState(i: MigrationNoticeInput): MigrationNoticeState {
  if (i.marker === 'dismissed' || i.marker === 'imported') return 'hide'
  if (i.mode === 'off' || isLegacyBrowserOrigin(i.pageOrigin) || !i.server) return 'hide'
  if (i.server.legacyOrigins.length || (i.server.legacyImport?.at != null && isLegacyBrowserOrigin(i.server.legacyImport.origin))) return 'imported'
  return i.server.legacyImport ? 'show' : 'maybe'
}

/** The notice wording for a state ('' when nothing shows). */
export function migrationNoticeText(state: MigrationNoticeState): string {
  return state === 'show' ? MIGRATE_NOTICE_TEXT : state === 'maybe' ? MIGRATE_NOTICE_TEXT_MAYBE : ''
}
