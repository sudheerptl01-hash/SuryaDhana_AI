/**
 * In-app settings import from the old browser terminal (page review 5 Nov 2026, M35). Pure: no DOM, no fetch, so
 * `node ui/components/desktop/__tests__/desktop.check.ts` runs it directly.
 *
 * Why a page on :3000: the owner's watchlist and pins live only in the localStorage of the browser that used
 * http://localhost:3000, and only a page on that origin can read it. ui-api serves a one-shot page there on the
 * owner's click (routers/prefs.py, POST /api/prefs/legacy-import), reading exactly the SYNC keys below (the keys the
 * sync code's own legacy import reads), and runs the fill-only legacy import when the owner clicks IMPORT on it: a
 * value the owner already set in the app is never replaced, so nothing is overwritten without a click.
 *
 * The offer replaces the permanent "not imported yet" banner: a one-time toast (marker OFFER_KEY), then a quiet entry
 * on GO (IMPORT / SETTINGS) and in MORE ▾ for as long as the server proves nothing was imported.
 */
import { SYNC_KEYS } from './keys'
import { migrationNoticeState, type ServerProvenance } from './migration'

/** LOCAL key (keys.ts): 'seen' once the one-time toast was shown on this origin. */
export const OFFER_KEY = 'suryadhana.migrate.offer.v1'
/** Opens the import dialog from anywhere (GO `IMPORT`, MORE ▾, the toast). */
export const OPEN_IMPORT_EVENT = 'suryadhana:open-settings-import'

/** The keys the import page reads: every SYNC key (the server's fill-only import decides what is filled). */
export function importKeys(): string[] {
  return [...SYNC_KEYS]
}

export type ImportPageState = 'idle' | 'waiting' | 'done' | 'expired' | 'stopped' | 'closed' | 'port_busy' | 'failed'

export interface ImportPageStatus {
  state: ImportPageState
  url: string | null
  urls: string[]
  port: number | null
  expiresAt: number | null
  imported: string[]
  skipped: string[]
  rejected: string[]
  found: number | null
  detail: string | null
}

const STATES: readonly ImportPageState[] = ['idle', 'waiting', 'done', 'expired', 'stopped', 'closed', 'port_busy', 'failed']
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** GET/POST /api/prefs/legacy-import → a validated status; a malformed body reads as 'failed' with the reason. */
export function parseImportStatus(raw: unknown): ImportPageStatus {
  const o = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {}
  const state = typeof o.state === 'string' && (STATES as readonly string[]).includes(o.state) ? (o.state as ImportPageState) : 'failed'
  const url = typeof o.url === 'string' && /^http:\/\/(localhost|127\.0\.0\.1):\d{2,5}\/import\?t=[A-Za-z0-9_-]{16,}$/.test(o.url) ? o.url : null
  return {
    state: state === 'waiting' && !url ? 'failed' : state,
    url,
    urls: strs(o.urls).filter((u) => /^http:\/\/(localhost|127\.0\.0\.1):\d{2,5}\/import\?t=/.test(u)),
    port: num(o.port),
    expiresAt: num(o.expires_at),
    imported: strs(o.imported),
    skipped: strs(o.skipped),
    rejected: strs(o.rejected),
    found: num(o.found),
    detail: typeof o.detail === 'string' ? o.detail.slice(0, 300) : state === 'failed' && !Object.keys(o).length ? 'no answer from ui-api' : null,
  }
}

const NAMES: Record<string, string> = { 'suryadhana.watchlist': 'watchlist', 'newsTerminal.pins.v1': 'pins' }
const name = (k: string) => NAMES[k] ?? k

/** One line for the dialog: what the import page is doing or did (key names, never values). */
export function importStatusText(s: ImportPageStatus, nowMs: number): string {
  switch (s.state) {
    case 'waiting': {
      const min = s.expiresAt ? Math.max(0, Math.ceil((s.expiresAt - nowMs) / 60_000)) : null
      return `Waiting: open the link below in the browser you used for the old terminal${min != null ? ` (it closes in ${min} min)` : ''}.`
    }
    case 'done': {
      if (!s.imported.length && !s.skipped.length) return 'The import page sent nothing: that browser holds no terminal settings.'
      const imp = s.imported.length ? `Imported ${s.imported.map(name).join(', ')}.` : 'Nothing new to import.'
      const kept = s.skipped.length ? ` Kept ${s.skipped.length} setting${s.skipped.length === 1 ? '' : 's'} you already set in the app (${s.skipped.map(name).join(', ')}).` : ''
      return imp + kept
    }
    case 'expired': return 'The import page closed after 10 minutes without an import. Start it again.'
    case 'stopped': return 'The import page was closed.'
    case 'closed': return 'ui-api restarted: start the import again.'
    case 'port_busy': return s.detail ?? 'Port 3000 is in use (the Next dev UI?): open http://localhost:3000 in your usual browser; it imports by itself.'
    case 'failed': return `The import could not start${s.detail ? `: ${s.detail}` : ''}.`
    default: return 'Not started.'
  }
}

/**
 * Should this origin offer the import? 'toast' the first time (the one-time toast), 'quiet' afterwards (GO and MORE ▾
 * only), 'none' once the server proves an import happened, on the :3000 origin itself, with sync off, or before the
 * server was read. Same evidence as the old banner (lib/prefs/migration.ts), without its permanent display.
 */
export function importOffer(i: { pageOrigin: string; mode: 'sync' | 'readonly' | 'off'; offerMarker: string | null; server: ServerProvenance | null }):
  'toast' | 'quiet' | 'none' {
  const st = migrationNoticeState({ pageOrigin: i.pageOrigin, mode: i.mode, marker: null, server: i.server })
  if (st !== 'show' && st !== 'maybe') return 'none'
  if (i.mode === 'readonly') return 'quiet'                       // QA audits: never a toast over the page under test
  return i.offerMarker === 'seen' ? 'quiet' : 'toast'
}

/** Toast copy for the offer ('show' = the server proves nothing was imported; 'maybe' = it cannot say). */
export function offerText(proven: boolean): string {
  return proven
    ? 'Your watchlist and pins from the old browser terminal are not here yet.'
    : 'If you used the old browser terminal, its watchlist and pins can be brought here.'
}
