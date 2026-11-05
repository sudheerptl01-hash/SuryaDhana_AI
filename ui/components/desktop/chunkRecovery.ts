/**
 * ChunkLoadError recovery: one guarded automatic reload.
 *
 * Why: after a release swap an open window may ask for a lazily loaded chunk of a build that is no longer
 * served (D1 carries old chunks forward, so this is the safety net, not the plan). A reload fetches the new
 * index.html and its chunks. Guard: at most one automatic reload per RELOAD_GUARD_MS per tab (sessionStorage),
 * so a chunk that is broken in the new build too can never cause a reload loop; and never while the server is
 * unreachable (a reload then would replace the terminal with the browser's / WKWebView's error page).
 * Without sessionStorage there is no guard, so there is no automatic reload either.
 */

export const RELOAD_GUARD_KEY = 'suryadhana.chunk-reload.v1'
export const RELOAD_GUARD_MS = 60_000

const CHUNK_RE = /ChunkLoadError|Loading (?:CSS )?chunk [\w./-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i

/** True for webpack/Next chunk failures (by name or by the messages Chromium, WebKit and Firefox use). */
export function isChunkLoadError(e: unknown): boolean {
  if (!e) return false
  if (typeof e === 'string') return CHUNK_RE.test(e)
  if (typeof e !== 'object') return false
  const err = e as { name?: unknown; message?: unknown }
  return (typeof err.name === 'string' && err.name === 'ChunkLoadError')
    || (typeof err.message === 'string' && CHUNK_RE.test(err.message))
}

function storage(): Storage | null {
  try {
    const s = window.sessionStorage
    const probe = '__sd_probe__'
    s.setItem(probe, '1')
    s.removeItem(probe)
    return s
  } catch {
    return null
  }
}

/** True when an automatic reload is allowed now (no reload in the last RELOAD_GUARD_MS, storage available). */
export function canAutoReload(now = Date.now()): boolean {
  const s = storage()
  if (!s) return false
  const last = Number(s.getItem(RELOAD_GUARD_KEY) || 0)
  return !Number.isFinite(last) || now - last >= RELOAD_GUARD_MS || last > now
}

function markAutoReload(now = Date.now()): void {
  try { storage()?.setItem(RELOAD_GUARD_KEY, String(now)) } catch { /* guarded by canAutoReload */ }
}

/** Any HTTP answer from the page's origin (even 404) = reachable; network error / 3 s timeout = not. */
export async function originReachable(timeoutMs = 3000): Promise<boolean> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = setTimeout(() => ctl?.abort(), timeoutMs)
  try {
    await fetch('/build-info.json', { cache: 'no-store', credentials: 'same-origin', signal: ctl?.signal })
    return true
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

export type RecoveryOutcome = 'reloading' | 'guarded' | 'unreachable'

/**
 * Reload once if allowed and the server answers. 'guarded' = a reload already happened recently (show the
 * error UI); 'unreachable' = server down (caller may retry later, e.g. when health recovers).
 */
export async function recoverFromChunkError(reload: () => void = () => window.location.reload()): Promise<RecoveryOutcome> {
  if (!canAutoReload()) return 'guarded'
  if (!(await originReachable())) return 'unreachable'
  if (!canAutoReload()) return 'guarded' // another error path won the race
  markAutoReload()
  reload()
  return 'reloading'
}
